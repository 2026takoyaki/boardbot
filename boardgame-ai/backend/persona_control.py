"""페르소나 전환 — 목소리·말투·화면 문구를 한 번에 바꾼다.

페르소나 하나를 바꾸면 세 곳이 같이 움직여야 한다.

    목소리     AudioManager (+ 새 목소리로 캐시 재prewarm)
    말투       agents.tools.lines (persona_lines/<id>.json)
    화면 문구  프론트에 내려간 카탈로그

셋 중 하나라도 빠지면 어긋난다 — 목소리만 바뀌고 말투는 그대로거나, 음성은
바뀌었는데 자막은 옛 문장이거나. 그래서 전환은 반드시 이 함수를 거친다.

여기가 backend에 있는 이유: audio는 agents를 몰라야 하고(계층), agents는
웹소켓을 몰라야 한다. 셋을 다 아는 곳은 backend뿐이다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agents.personas import PERSONAS, get_persona
from agents.tools import lines, tempo_pool
from audio.manager import AudioManager
from core.constants import MsgType
from core.envelope import WSMessage
from core.persona import Persona

logger = logging.getLogger(__name__)

Broadcast = Callable[[WSMessage], Awaitable[None]]

# 미리듣기로 들려줄 멘트.
#
# 페르소나마다 이미 변환해 둔 문장 중 하나를 그대로 쓴다. 미리듣기 전용 문장을
# 새로 만들면 그 줄만 변환본이 없어서 넷 다 중립 원문으로 나가고, 목소리만
# 다르고 말투는 똑같은 미리듣기가 된다 — 정작 고를 때 알아야 할 것이 말투다.
#
# 이 줄을 고른 이유는 넷의 차이가 가장 크게 벌어지기 때문이다.
#   샤갈    "여러분. 밤입니다. 다들 눈 감으세요. 훔쳐보면 샤갈!…"
#   충청도  "인자 밤 됐슈. 눈을 뜨든 감든 알아서 햐유~"
#   화난누나 "야 밤이잖아. 눈 감으라고. 아 진짜 몇 번을 말해."
#   할머니  "밤이다 이눔들아. 싹 다 눈 감어라."
PREVIEW_LINE_ID = "werewolf.night_start"


@dataclass(frozen=True)
class PersonaReport:
    """전환 결과. 로그와 디버그 엔드포인트가 읽는다."""

    persona: Persona
    applied: int          # 말투가 적용된 줄 수
    total: int            # 전체 멘트 수
    rejected: dict[str, list[str]]  # 검사에 걸린 줄과 사유
    prewarm: dict[str, int]         # 캐시 재합성 결과

    def summary(self) -> str:
        text = (
            f"persona={self.persona.id} voice={self.persona.voice_name} "
            f"말투 {self.applied}/{self.total}줄"
        )
        if self.rejected:
            text += f", 검사 실패 {len(self.rejected)}줄"
        return text


def catalog_message() -> WSMessage:
    """현재 말투가 반영된 화면 문구 목록.

    접속 시에는 hello에 실어 보내고, 전환 시에는 이 메시지로 따로 보낸다.
    hello로 다시 보내면 프론트가 새 접속으로 착각해 게임을 다시 시작한다.
    """
    return WSMessage(
        msg_type=MsgType.LINES_CATALOG.value,
        payload={"lines": lines.catalog(), "persona": lines.active_persona_id()},
    )


def persona_options() -> list[dict[str, object]]:
    """고를 수 있는 진행자 목록. 프론트 선택 UI가 그대로 그린다.

    지금 누가 활성인지도 같이 준다 — 프론트가 따로 물어보면 전환 도중에
    둘이 어긋난 상태로 그려질 수 있다.
    """
    active = lines.active_persona_id()
    return [
        {
            "id": p.id,
            "display_name": p.display_name,
            "description": p.description,
            "active": p.id == active,
        }
        for p in PERSONAS.values()
    ]


async def preview_persona(
    persona_id: str,
    audio_manager: AudioManager | None,
) -> str:
    """그 페르소나의 목소리·말투로 한 마디 들려준다. 전환하지는 않는다.

    전환은 캐시를 통째로 다시 데우는 일이라 몇십 초가 걸린다. 넷을 훑어보는
    동안 그걸 매번 하면 고를 수가 없다. 그래서 미리듣기는 목소리만 갈아끼워
    한 문장을 합성한다.

    Returns: 실제로 발화한 문장(빈 문자열이면 발화하지 못함).
    """
    if audio_manager is None:
        return ""
    persona = get_persona(persona_id)
    # 변환본을 직접 읽는다. lines.get()은 "지금 활성 페르소나" 기준이라
    # 미리듣기 대상이 아닌 사람의 말투가 나온다.
    converted, _ = lines.load_persona_lines(persona.id)
    text = converted.get(PREVIEW_LINE_ID) or lines.original(PREVIEW_LINE_ID) or ""
    if not text:
        return ""
    # 새로 누른 것이 앞의 것을 끊는다. 넷을 훑어보며 연달아 누르는 자리라,
    # 큐에 쌓이면 이미 관심이 떠난 목소리가 줄줄이 재생된다.
    await audio_manager.interrupt_interruptible("persona_preview")
    await audio_manager.enqueue_tts(
        text=text,
        agent="narrator",
        interruptible=True,
        voice=persona.voice_for(),
    )
    return text


_apply_task: asyncio.Task[None] | None = None


def schedule_persona_switch(
    persona_id: str,
    audio_manager: AudioManager | None = None,
    broadcast: Broadcast | None = None,
) -> None:
    """전환을 뒤에서 돌린다. 이미 돌고 있던 전환은 버린다.

    전환은 캐시를 통째로 다시 데우는 일이라 오래 걸린다. 고르는 사람은 그
    사이에도 다른 걸 눌러볼 수 있는데, 그때마다 새 prewarm이 쌓이면 API를
    떼로 두드리고 마지막에 누른 것이 가장 늦게 끝날 수도 있다. 앞의 것을
    취소해야 "마지막으로 고른 사람"이 이긴다.
    """
    global _apply_task
    if _apply_task is not None and not _apply_task.done():
        _apply_task.cancel()

    async def _run() -> None:
        try:
            await apply_persona(persona_id, audio_manager, broadcast)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 전환에 실패해도 진행은 멈추지 않는다. 앞 페르소나로 계속 말한다.
            logger.exception("페르소나 전환 실패 (%s)", persona_id)

    _apply_task = asyncio.create_task(_run())


async def _push_catalog(broadcast: Broadcast | None) -> None:
    """새 말투의 화면 문구를 접속 중인 화면에 밀어준다."""
    if broadcast is None:
        return
    try:
        await broadcast(catalog_message())
    except Exception:
        # 화면 갱신에 실패해도 음성은 새 페르소나로 나간다. 자막이 잠시
        # 옛 문장으로 남을 뿐이라 진행을 막지 않는다.
        logger.exception("페르소나 카탈로그 broadcast 실패")


_tempo_task: asyncio.Task[None] | None = None


def _schedule_tempo_pool(persona: Persona, audio_manager: AudioManager) -> None:
    """재촉 변형을 뒤에서 만들어 캐시에 올린다.

    앞선 전환의 작업이 남아 있으면 취소한다 — 옛 페르소나 목소리로 합성한
    문장이 뒤늦게 목록에 얹히면, 지금 페르소나와 섞여 나간다.
    """
    global _tempo_task
    if _tempo_task is not None and not _tempo_task.done():
        _tempo_task.cancel()

    async def _run() -> None:
        try:
            texts = await tempo_pool.regenerate(persona)
            # 만드는 동안 사람이 페르소나를 또 바꿨을 수 있다. 그러면 이건
            # 남의 목소리로 합성될 문장이라 버린다.
            if lines.active_persona_id() != persona.id:
                logger.info("[tempo] 페르소나가 바뀌어 변형을 버림 (%s)", persona.id)
                tempo_pool.clear()
                return
            await audio_manager.add_static_texts(texts)
        except asyncio.CancelledError:
            raise
        except Exception:
            # 변형이 없으면 고정 멘트로 재촉한다. 진행이 막히지는 않는다.
            logger.exception("[tempo] 변형 준비 실패 — 고정 멘트로 재촉합니다")

    _tempo_task = asyncio.create_task(_run())


async def apply_persona(
    persona_id: str | None,
    audio_manager: AudioManager | None = None,
    broadcast: Broadcast | None = None,
    prewarm: bool = True,
) -> PersonaReport:
    """페르소나를 적용한다. 없는 id면 기본 페르소나로 떨어진다.

    prewarm=False는 부팅 시 TTS가 없을 때/테스트용 — 합성 없이 설정만 바꾼다.
    broadcast를 주면 접속 중인 화면에도 새 문구를 밀어준다.
    """
    persona = get_persona(persona_id)

    # 말투 먼저. 화면·음성이 같은 카탈로그를 보므로 이걸 먼저 바꿔야
    # 뒤이어 나가는 카탈로그가 새 문장을 담는다.
    applied, rejected = lines.use_persona(persona.id)

    tempo_pool.clear()

    # 화면 문구는 여기서 바로 내보낸다. 아래 prewarm은 음성 캐시를 통째로 다시
    # 데우는 일이라 수십 초가 걸리는데, 화면에 글자를 그리는 데는 그게 필요
    # 없다. 뒤에 두면 진행자를 바꾼 뒤 한참 동안 옛 문장이 떠 있는다.
    await _push_catalog(broadcast)

    prewarm_stats: dict[str, int] = {}
    if audio_manager is not None:
        # 미리 만들어 둘 문장 목록을 먼저 갱신한다. 이게 옛 문장으로 남아 있으면
        # 새 페르소나로 데우는 것이 아니라 아무도 안 쓸 문장을 데우게 된다.
        audio_manager.set_line_catalog(
            lines.static_texts(),
            lines.session_templates(),
            lines.delivery_static(),
            lines.delivery_templates(),
        )
        prewarm_stats = await audio_manager.set_persona(persona, prewarm=prewarm)
        # 재촉 변형은 여기서 기다리지 않는다. LLM 생성만 10초가 걸려 부팅이
        # 그만큼 늦어지는데, 정작 재촉이 필요한 시점은 한참 뒤다.
        if prewarm:
            _schedule_tempo_pool(persona, audio_manager)

    report = PersonaReport(
        persona=persona,
        applied=applied,
        total=len(lines.LINES),
        rejected=rejected,
        prewarm=prewarm_stats,
    )
    logger.info("%s", report.summary())
    if rejected:
        logger.warning("persona lines 검사 실패: %s", rejected)
    return report
