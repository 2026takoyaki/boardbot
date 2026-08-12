"""TTS 사전 합성(prewarm) 로직.

- prewarm_static(engine): 부팅 시 1회. STATIC_LINES를 narrator 보이스로 합성.
- prewarm_session(engine, session_id, player_names): 좌석 등록 완료 시.
    각 플레이어 × SESSION_TEMPLATES 변형을 합성.
- wipe_session(session_id): 플레이어 변경/초기화 시 해당 세션 캐시 제거.

prewarm은 백그라운드 asyncio.gather로 병렬화하되 Semaphore가 동시성을 제한.
실패한 항목은 로그만 남기고 전체는 계속 진행 (런타임에 cache miss로 다시 시도됨).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from pathlib import Path

from audio.catalog import (
    EXCITED_LINES,
    SESSION_CACHE_DIR,
    STATIC_LINES,
    expand_session_lines,
)
from audio.tts_engine import TTSEngine
from core.persona import DELIVERY_EXCITED, Persona

logger = logging.getLogger(__name__)


async def prewarm_static(engine: TTSEngine, persona: Persona) -> dict[str, int]:
    """STATIC_LINES + EXCITED_LINES를 페르소나의 목소리로 합성.

    페르소나가 바뀌면 캐시 키가 전부 달라지므로 이 함수를 다시 불러야 한다.

    Returns: {"total": N, "cached": M, "synthesized": K, "failed": F}
    """
    base_voice = persona.voice_for()
    excited_voice = persona.voice_for(DELIVERY_EXCITED)

    # 페르소나가 고른 엔진 기준으로 판단한다. 기본 엔진만 보면 Typecast
    # 페르소나가 쓰는 엔진이 아니라 다른 엔진을 보고 건너뛰는 일이 생긴다.
    if not engine.is_available(base_voice):
        logger.warning(
            "prewarm_static: %s 엔진을 쓸 수 없어 건너뜁니다 (런타임에 STATIC이 실패함)",
            base_voice.provider,
        )
        total = len(STATIC_LINES) + len(EXCITED_LINES)
        return {"total": total, "cached": 0, "synthesized": 0, "failed": 0}

    # (voice, text) 쌍으로 통합 처리
    pairs: list[tuple[object, str]] = []
    pairs.extend((base_voice, t) for t in STATIC_LINES)
    pairs.extend((excited_voice, t) for t in EXCITED_LINES)

    cached = 0
    to_synth: list[tuple[object, str]] = []
    for voice, text in pairs:
        if engine.cache_hit(text, voice, "static") is not None:  # type: ignore[arg-type]
            cached += 1
        else:
            to_synth.append((voice, text))

    results = await asyncio.gather(
        *(engine.synthesize(text, voice, "static") for voice, text in to_synth),  # type: ignore[arg-type]
        return_exceptions=True,
    )
    synthesized = sum(1 for r in results if isinstance(r, Path))
    failed = len(results) - synthesized

    logger.info(
        "prewarm_static: total=%d cached=%d synthesized=%d failed=%d (static=%d + excited=%d)",
        len(pairs), cached, synthesized, failed, len(STATIC_LINES), len(EXCITED_LINES),
    )
    return {
        "total": len(pairs),
        "cached": cached,
        "synthesized": synthesized,
        "failed": failed,
    }


async def prewarm_session(
    engine: TTSEngine,
    session_id: str,
    player_names: list[str],
    persona: Persona | None = None,
) -> dict[str, int]:
    """플레이어 이름 슬롯이 채워진 멘트를 사전 합성.

    좌석 등록 완료 직후 호출. session_id는 플레이어 구성과 1:1 매핑되어야 한다
    (예: 플레이어 이름 정렬 hash).
    """
    # 페르소나가 없으면 엔진 기본 목소리로 떨어진다(테스트 경로).
    voice = persona.voice_for() if persona is not None else None

    if not engine.is_available(voice):
        logger.warning("prewarm_session: TTS 엔진을 쓸 수 없어 건너뜁니다 (session=%s)", session_id)
        return {"total": 0, "cached": 0, "synthesized": 0, "failed": 0}

    if not player_names:
        return {"total": 0, "cached": 0, "synthesized": 0, "failed": 0}
    expanded = expand_session_lines(player_names)  # [(template, formatted), ...]
    formatted_lines = [text for _, text in expanded]

    cached = 0
    to_synth: list[str] = []
    for text in formatted_lines:
        if engine.cache_hit(text, voice, "session", session_id=session_id) is not None:
            cached += 1
        else:
            to_synth.append(text)

    results = await asyncio.gather(
        *(
            engine.synthesize(t, voice, "session", session_id=session_id)
            for t in to_synth
        ),
        return_exceptions=True,
    )
    synthesized = sum(1 for r in results if isinstance(r, Path))
    failed = len(results) - synthesized

    logger.info(
        "prewarm_session(%s, players=%s): total=%d cached=%d synthesized=%d failed=%d",
        session_id, player_names,
        len(formatted_lines), cached, synthesized, failed,
    )
    return {
        "total": len(formatted_lines),
        "cached": cached,
        "synthesized": synthesized,
        "failed": failed,
    }


def wipe_session(session_id: str) -> bool:
    """플레이어 변경/초기화 시 해당 세션 디렉토리 삭제.

    Returns: 삭제했으면 True, 디렉토리 없었으면 False.
    """
    target = SESSION_CACHE_DIR / session_id
    if not target.exists():
        return False
    shutil.rmtree(target, ignore_errors=True)
    logger.info("wipe_session: removed %s", target)
    return True


def make_session_id(player_names: list[str]) -> str:
    """플레이어 이름 목록 → 결정적 session_id.

    같은 플레이어 구성이면 같은 id → 캐시 재사용. 순서 무관.
    """
    import hashlib

    key = "|".join(sorted(player_names))
    return "sess_" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
