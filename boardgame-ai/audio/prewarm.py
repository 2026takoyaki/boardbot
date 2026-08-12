"""TTS 사전 합성(prewarm) 로직.

미리 만들어 둘 수 있는 문장을 먼저 합성해 캐시에 넣는다. 게임 중 첫 발화에
합성 지연이 붙으면 진행이 끊기기 때문이다.

- prewarm_static: 부팅 시, 그리고 페르소나가 바뀔 때마다.
- prewarm_session: 좌석 등록 완료 시. 이름 슬롯을 각 플레이어로 채워 합성.
- wipe_session: 플레이어 변경/초기화 시 해당 세션 캐시 제거.

**문장 목록은 인자로 받는다.** audio 계층은 어떤 문장이 있는지 모른다 —
그건 에이전트(agents/tools/lines.py)가 소유하고, 페르소나에 따라 달라진다.
여기서 고정 목록을 들고 있으면 페르소나를 바꿨을 때 옛 문장을 합성해두고
정작 발화되는 문장은 캐시에 없는 상태가 된다.

병렬화는 asyncio.gather로 하되 Semaphore가 동시성을 제한한다.
실패한 항목은 로그만 남기고 전체는 계속 진행(런타임에 cache miss로 재시도).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
from collections.abc import Iterable
from pathlib import Path

from audio.catalog import SESSION_CACHE_DIR
from audio.tts_engine import TTSEngine
from core.persona import Persona

logger = logging.getLogger(__name__)


async def prewarm_static(
    engine: TTSEngine,
    persona: Persona,
    texts: Iterable[str],
) -> dict[str, int]:
    """슬롯 없는 문장들을 페르소나 목소리로 합성.

    페르소나가 바뀌면 캐시 키가 전부 달라지므로 이 함수를 다시 불러야 한다.

    Returns: {"total": N, "cached": M, "synthesized": K, "failed": F}
    """
    items = [t for t in texts if t.strip()]
    voice = persona.voice_for()

    if not engine.is_available(voice):
        logger.warning(
            "prewarm_static: %s 엔진을 쓸 수 없어 건너뜁니다 (런타임에 합성 지연이 붙음)",
            voice.provider,
        )
        return {"total": len(items), "cached": 0, "synthesized": 0, "failed": 0}

    cached = 0
    to_synth: list[str] = []
    for text in items:
        if engine.cache_hit(text, voice, "static") is not None:
            cached += 1
        else:
            to_synth.append(text)

    results = await asyncio.gather(
        *(engine.synthesize(t, voice, "static") for t in to_synth),
        return_exceptions=True,
    )
    synthesized = sum(1 for r in results if isinstance(r, Path))
    failed = len(results) - synthesized

    logger.info(
        "prewarm_static(%s): total=%d cached=%d synthesized=%d failed=%d",
        persona.id, len(items), cached, synthesized, failed,
    )
    return {
        "total": len(items),
        "cached": cached,
        "synthesized": synthesized,
        "failed": failed,
    }


async def prewarm_session(
    engine: TTSEngine,
    session_id: str,
    texts: Iterable[str],
    persona: Persona | None = None,
) -> dict[str, int]:
    """이름이 채워진 문장들을 사전 합성.

    좌석 등록 완료 직후 호출. session_id는 플레이어 구성과 1:1 매핑되어야 한다
    (예: 플레이어 이름 정렬 hash).
    """
    items = [t for t in texts if t.strip()]
    voice = persona.voice_for() if persona is not None else None

    if not items:
        return {"total": 0, "cached": 0, "synthesized": 0, "failed": 0}

    if not engine.is_available(voice):
        logger.warning("prewarm_session: TTS 엔진을 쓸 수 없어 건너뜁니다 (session=%s)", session_id)
        return {"total": len(items), "cached": 0, "synthesized": 0, "failed": 0}

    cached = 0
    to_synth: list[str] = []
    for text in items:
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
        "prewarm_session(%s): total=%d cached=%d synthesized=%d failed=%d",
        session_id, len(items), cached, synthesized, failed,
    )
    return {
        "total": len(items),
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
