"""Typecast TTS 어댑터.

캐릭터가 뚜렷한 한국어 보이스가 필요해서 쓴다. 범용 TTS는 표준 아나운서
톤만 있어서 밈 말투나 사투리 캐릭터를 목소리로 표현할 수 없다.

환경:
    TYPECAST_API_KEY   .env에 넣는다

API (https://typecast.ai/docs/ko/quickstart):
    POST https://api.typecast.ai/v1/text-to-speech
    헤더  X-API-KEY
    body  {"text", "voice_id", "model", "prompt": {...}, "output": {...}}
    응답  오디오 바이너리

파라미터 대응:
    VoiceConfig.name           → voice_id
    VoiceConfig.model          → model (기본 ssfm-v30)
    VoiceConfig.speaking_rate  → output.audio_tempo   (0.5~2.0)
    VoiceConfig.pitch          → output.audio_pitch   (-12~12 반음)
    VoiceConfig.emotion        → prompt.emotion_type
"""

from __future__ import annotations

import logging
import os
import random
import time
from collections.abc import Mapping

from core.persona import VoiceConfig

logger = logging.getLogger(__name__)

_ENDPOINT = "https://api.typecast.ai/v1/text-to-speech"
_VOICES_ENDPOINT = "https://api.typecast.ai/v2/voices"
_DEFAULT_MODEL = "ssfm-v30"

# 잠시 기다리면 풀리는 상태들. 부팅 prewarm은 100줄 넘는 문장을 한꺼번에 쏘기
# 때문에 rate limit(429)에 정면으로 부딪힌다. 재시도가 없으면 걸린 줄이 캐시에서
# 그대로 빠지고, 그 문장은 게임 중에 실시간 합성을 기다리게 된다.
_RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
_MAX_ATTEMPTS = 3
# 상위 synthesize()가 20초 wait_for로 감싸므로 대기가 그 안에 들어와야 한다.
# 요청 시간까지 감안해 한 번 대기를 5초로 자른다.
_MAX_BACKOFF = 5.0

# API가 받아주는 범위. 넘겨서 400을 받느니 여기서 잘라 보낸다 —
# 페르소나 값이 조금 튀었다고 그 멘트가 통째로 사라지면 안 된다.
_TEMPO_RANGE = (0.5, 2.0)
_PITCH_RANGE = (-12, 12)
_INTENSITY_RANGE = (0.0, 2.0)

# 모델이 아는 감정. 여기 없는 값을 보내면 422로 그 멘트가 통째로 사라진다 —
# 감정 하나 때문에 발화를 잃느니 감정을 빼고 말하게 한다.
EMOTIONS: dict[str, frozenset[str]] = {
    "ssfm-v30": frozenset(
        {"normal", "happy", "sad", "angry", "whisper", "toneup", "tonedown"}
    ),
    "ssfm-v21": frozenset({"normal", "happy", "sad", "angry"}),
}


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


class TypecastProvider:
    name = "typecast"
    audio_ext = "wav"

    def __init__(self, timeout: float = 20.0) -> None:
        self._timeout = timeout
        self._key = os.environ.get("TYPECAST_API_KEY", "").strip()
        self._reason = "" if self._key else "TYPECAST_API_KEY 미설정"
        self._httpx = None
        if self._key:
            try:
                import httpx

                self._httpx = httpx
            except ImportError:
                self._reason = "httpx 미설치"

    def is_available(self) -> bool:
        return bool(self._key) and self._httpx is not None

    def unavailable_reason(self) -> str:
        return self._reason

    def _headers(self) -> dict[str, str]:
        return {"X-API-KEY": self._key, "Content-Type": "application/json"}

    def _payload(self, text: str, voice: VoiceConfig) -> dict[str, object]:
        model = voice.model or _DEFAULT_MODEL
        payload: dict[str, object] = {
            "text": text,
            "voice_id": voice.name,
            "model": model,
            "output": {
                "audio_format": self.audio_ext,
                "audio_tempo": _clamp(voice.speaking_rate, *_TEMPO_RANGE),
                "audio_pitch": _clamp(voice.pitch, *_PITCH_RANGE),
            },
        }
        # emotion_type은 감정 이름이 아니라 감정을 고르는 방식이다.
        # preset = 맥락을 보지 않고 지정한 감정을 그대로 적용. 진행 멘트는
        # 매번 같은 톤이어야 하므로 smart(맥락 추론)보다 preset이 맞다.
        if voice.emotion:
            allowed = EMOTIONS.get(model)
            if allowed is not None and voice.emotion not in allowed:
                logger.warning(
                    "%s가 모르는 감정 %r — 감정 없이 합성합니다 (가능: %s)",
                    model, voice.emotion, ", ".join(sorted(allowed)),
                )
            else:
                prompt: dict[str, object] = {
                    "emotion_type": "preset",
                    "emotion_preset": voice.emotion,
                }
                if voice.emotion_intensity is not None:
                    prompt["emotion_intensity"] = _clamp(
                        voice.emotion_intensity, *_INTENSITY_RANGE
                    )
                payload["prompt"] = prompt
        return payload

    def _backoff_seconds(self, response: object, attempt: int) -> float:
        """다음 시도까지 기다릴 시간.

        서버가 Retry-After를 주면 그 말을 듣는다 — 우리가 어림짐작한 값보다
        정확하다. 없으면 지수 백오프에 지터를 섞는다. 지터가 필요한 이유는
        동시 요청들이 한꺼번에 429를 받기 때문이다. 같은 간격으로 재시도하면
        떼로 몰려가 또 같이 걸린다.
        """
        headers = getattr(response, "headers", None)
        raw = headers.get("Retry-After") if isinstance(headers, Mapping) else None
        if raw is not None:
            try:
                requested: float = float(str(raw))
            except ValueError:
                requested = -1.0
            if requested >= 0:
                return min(requested, _MAX_BACKOFF)
        backoff: float = 0.5 * (2**attempt) + random.uniform(0, 0.4)
        return min(backoff, _MAX_BACKOFF)

    def synthesize_sync(self, text: str, voice: VoiceConfig) -> bytes:
        assert self._httpx is not None
        if not voice.name:
            # 페르소나에 voice_id를 아직 안 넣은 상태. 빈 값으로 요청하면 400이
            # 오는데, 그 에러만 보면 원인이 API 문제인지 설정 누락인지 모른다.
            raise RuntimeError(
                "voice_id가 비어 있습니다. agents/personas.py의 voice_name을 "
                "채우세요 (python tools/tts_voices.py 로 id 확인)."
            )
        payload = self._payload(text, voice)
        for attempt in range(_MAX_ATTEMPTS):
            response = self._httpx.post(
                _ENDPOINT,
                headers=self._headers(),
                json=payload,
                timeout=self._timeout,
            )
            if response.status_code < 400:
                return bytes(response.content)

            # 400·422 같은 것은 다시 보내도 같은 답이 온다. 요청 자체가 틀린
            # 것이라 재시도는 시간만 버린다.
            last = attempt == _MAX_ATTEMPTS - 1
            if response.status_code not in _RETRY_STATUS or last:
                # 본문에 사유가 담겨 온다. 상태 코드만 남기면 원인을 못 찾는다.
                raise RuntimeError(
                    f"Typecast {response.status_code}: {response.text[:300]}"
                )

            delay = self._backoff_seconds(response, attempt)
            logger.debug(
                "Typecast %d — %.1fs 후 재시도 (%d/%d) %r",
                response.status_code, delay, attempt + 1, _MAX_ATTEMPTS, text[:20],
            )
            time.sleep(delay)

        # _MAX_ATTEMPTS >= 1 이면 위 루프에서 반드시 반환하거나 raise 한다.
        raise RuntimeError("Typecast: 재시도 한도 초과")

    def list_voices(self) -> list[dict[str, object]]:
        """쓸 수 있는 보이스 목록. tools/tts_voices.py가 쓴다.

        페르소나에 넣을 voice_id를 여기서 찾는다 — 이름(칼란, 박창수 등)만
        알고 id를 모르는 상태에서 시작하기 때문이다.
        """
        assert self._httpx is not None
        response = self._httpx.get(
            _VOICES_ENDPOINT, headers=self._headers(), timeout=self._timeout
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict):
            for key in ("voices", "data", "result"):
                if isinstance(data.get(key), list):
                    return list(data[key])
            return []
        return list(data) if isinstance(data, list) else []
