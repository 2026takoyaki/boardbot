"""TTS 합성 + 디스크 캐시.

캐시 정책:
- cache_key = sha1(엔진 + 보이스 설정 + 텍스트). 엔진이 키에 들어가야
  엔진을 바꿨을 때 옛 음성이 재생되지 않는다.
- 결과 wav는 cache_layer에 따라 static/session/<id>/dynamic/ 하위에 저장.
- synthesize() 호출 시 캐시 hit이면 API 호출 0회, 즉시 Path 반환.

동시성:
- asyncio.Semaphore(max_concurrency)로 동시 API 호출 제한 → quota burst 방지.
  기본값 2, TTS_MAX_CONCURRENCY로 조절.

장애 처리:
- 엔진 실패/타임아웃 시 None 반환. 상위(AudioManager)가 text-only fallback 결정.

환경:
- 합성 자체는 audio/tts/ 아래 어댑터가 한다. 필요한 키도 거기에 적혀 있다.
- 엔진을 쓸 수 없으면 is_available() == False, synthesize는 즉시 None.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
from pathlib import Path

from audio.catalog import (
    DEFAULT_VOICE,
    DYNAMIC_CACHE_DIR,
    SESSION_CACHE_DIR,
    STATIC_CACHE_DIR,
    VoiceConfig,
)
from audio.tts.base import DEFAULT_PROVIDER, TTSProvider, get_provider

logger = logging.getLogger(__name__)


def _env_int(name: str, default: int) -> int:
    """정수 환경변수. 값이 이상하면 기본값 — 오타 하나로 서버가 안 뜨면 곤란하다."""
    try:
        value = int(os.environ.get(name, "").strip())
    except ValueError:
        return default
    return value if value > 0 else default


def _bench_log_hit(key: str, layer: str) -> None:
    """Benchmark hook: 캐시 hit. BENCH_TRACE=0이면 no-op."""
    try:
        from benchmarks.common.trace_setup import bench_log, is_bench
        if is_bench():
            bench_log().info("tts_synth_done %s hit=1 layer=%s elapsed_ms=0.0", key, layer)
    except Exception:
        pass


def _bench_log_miss(key: str, layer: str, elapsed_ms: float) -> None:
    """Benchmark hook: 캐시 miss(합성 발생). BENCH_TRACE=0이면 no-op."""
    try:
        from benchmarks.common.trace_setup import bench_log, is_bench
        if is_bench():
            bench_log().info(
                "tts_synth_done %s hit=0 layer=%s elapsed_ms=%.3f", key, layer, elapsed_ms,
            )
    except Exception:
        pass


CacheLayer = str  # "static" | "session" | "dynamic"


def _cache_dir_for(layer: CacheLayer, session_id: str | None = None) -> Path:
    if layer == "static":
        return STATIC_CACHE_DIR
    if layer == "session":
        if not session_id:
            raise ValueError("session layer requires session_id")
        return SESSION_CACHE_DIR / session_id
    if layer == "dynamic":
        return DYNAMIC_CACHE_DIR
    raise ValueError(f"unknown cache layer: {layer}")


# 캐시 키 스키마 버전. 키 구성이 바뀌면 올린다 — 옛 파일이 새 규칙으로 hit되어
# 엉뚱한 목소리가 재생되는 것을 막는다.
_CACHE_SCHEMA = "v2"


def _make_cache_key(text: str, voice: VoiceConfig) -> str:
    """텍스트 + 보이스 설정 → sha1 16자 hex.

    엔진(provider)이 반드시 들어가야 한다. 안 넣으면 Typecast로 바꿔도
    옛 엔진이 만든 파일이 그대로 hit되어 목소리가 안 바뀐다.
    """
    raw = "|".join([
        _CACHE_SCHEMA,
        voice.provider,
        voice.model or "",
        voice.emotion or "",
        f"{voice.emotion_intensity}",
        voice.name,
        voice.language_code,
        f"{voice.speaking_rate}",
        f"{voice.pitch}",
        text,
    ])
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


class TTSEngine:
    """텍스트 → 오디오 파일. 엔진은 보이스가 지정한다.

    Usage:
        engine = TTSEngine()
        path = await engine.synthesize("안녕하세요", voice, "static")
    """

    def __init__(
        self, max_concurrency: int | None = None, timeout_sec: float = 20.0
    ) -> None:
        # 부팅 prewarm은 100줄 넘는 문장을 한꺼번에 쏜다. 동시에 많이 보낼수록
        # 빨리 데워지지만 rate limit(429)에 걸린 줄은 캐시에 못 들어가고, 그
        # 문장은 게임 중에 실시간 합성을 기다리게 된다. 부팅은 어차피 비전
        # 모델 로딩으로 느리니 여기서는 확실히 채우는 쪽을 택한다.
        # 계정 한도가 다르면 TTS_MAX_CONCURRENCY로 조절한다.
        if max_concurrency is None:
            max_concurrency = _env_int("TTS_MAX_CONCURRENCY", 2)
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._timeout = timeout_sec
        # 엔진은 보이스마다 다를 수 있다(페르소나가 고른다). 한 번 만든 어댑터는
        # 재사용한다 — 매번 새로 만들면 커넥션 풀이 낭비된다.
        self._providers: dict[str, TTSProvider] = {}

    def provider_for(self, voice: VoiceConfig) -> TTSProvider:
        key = voice.provider or DEFAULT_PROVIDER
        if key not in self._providers:
            provider = get_provider(key)
            self._providers[key] = provider
            if provider.is_available():
                logger.info("TTS 엔진 준비됨: %s", provider.name)
            else:
                logger.warning(
                    "TTS 엔진 사용 불가: %s (%s)", provider.name, provider.unavailable_reason()
                )
        return self._providers[key]

    def is_available(self, voice: VoiceConfig | None = None) -> bool:
        """합성 가능 여부. 보이스를 주면 그 엔진 기준으로 판단한다."""
        return self.provider_for(voice or DEFAULT_VOICE).is_available()

    def cache_path(
        self,
        text: str,
        voice: VoiceConfig | None = None,
        cache_layer: CacheLayer = "dynamic",
        session_id: str | None = None,
    ) -> Path:
        """text/voice/layer로 결정되는 캐시 파일 경로(존재 여부 무관)."""
        v = voice or DEFAULT_VOICE
        key = _make_cache_key(text, v)
        ext = self.provider_for(v).audio_ext
        return _cache_dir_for(cache_layer, session_id) / f"{key}.{ext}"

    def cache_hit(
        self,
        text: str,
        voice: VoiceConfig | None = None,
        cache_layer: CacheLayer = "dynamic",
        session_id: str | None = None,
    ) -> Path | None:
        path = self.cache_path(text, voice, cache_layer, session_id)
        if path.exists():
            # Benchmark hook: cache_hit_rate 지표가 정확히 잡히도록 hit을 여기서 기록.
            # 호출부(AudioManager 등)가 cache_hit→synthesize 순으로 단락 평가하므로
            # synthesize() 안의 hit 로그는 거의 안 찍힘.
            _bench_log_hit(path.stem, cache_layer)
            return path
        return None

    async def synthesize(
        self,
        text: str,
        voice: VoiceConfig | None = None,
        cache_layer: CacheLayer = "dynamic",
        session_id: str | None = None,
    ) -> Path | None:
        """텍스트 → 오디오 파일. 캐시 hit이면 즉시 반환, miss면 엔진 호출.

        반환: 캐시 파일 경로. 합성 실패 또는 엔진 사용 불가 시 None.
        """
        v = voice or DEFAULT_VOICE
        provider = self.provider_for(v)
        path = self.cache_path(text, v, cache_layer, session_id)

        if path.exists():
            # hit 로그는 cache_hit() 경로에서 기록 (호출부가 cache_hit 단락 평가하므로
            # synthesize()로는 거의 안 들어옴). 만약 호출부가 synthesize()를 직접 부르고
            # 캐시가 있는 경우엔 여기서도 기록해 둔다.
            _bench_log_hit(path.stem, cache_layer)
            return path

        if not provider.is_available():
            logger.debug(
                "synthesize: %s 사용 불가(%s) — %r 건너뜀",
                provider.name, provider.unavailable_reason(), text[:30],
            )
            return None

        path.parent.mkdir(parents=True, exist_ok=True)

        import time as _t
        synth_start = _t.time()
        try:
            async with self._semaphore:
                wav_bytes = await asyncio.wait_for(
                    asyncio.to_thread(provider.synthesize_sync, text, v),
                    timeout=self._timeout,
                )
        except TimeoutError:
            logger.warning("synthesize: %.1fs 타임아웃 — %r", self._timeout, text[:30])
            return None
        except Exception:
            logger.exception("synthesize: %s 호출 실패 — %r", provider.name, text[:30])
            return None

        if not wav_bytes:
            return None

        # 원자성: 임시 파일에 쓰고 rename → 부분 쓰기로 인한 깨진 캐시 방지.
        tmp_path = path.with_suffix(path.suffix + ".tmp")
        tmp_path.write_bytes(wav_bytes)
        tmp_path.replace(path)
        elapsed_ms = (_t.time() - synth_start) * 1000
        _bench_log_miss(path.stem, cache_layer, elapsed_ms)
        logger.info("synthesized %d bytes → %s", len(wav_bytes), path.name)
        return path
