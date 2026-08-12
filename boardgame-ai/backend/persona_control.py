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

import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from agents.personas import get_persona
from agents.tools import lines
from audio.manager import AudioManager
from core.constants import MsgType
from core.envelope import WSMessage
from core.persona import Persona

logger = logging.getLogger(__name__)

Broadcast = Callable[[WSMessage], Awaitable[None]]


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

    prewarm_stats: dict[str, int] = {}
    if audio_manager is not None:
        # 미리 만들어 둘 문장 목록을 먼저 갱신한다. 이게 옛 문장으로 남아 있으면
        # 새 페르소나로 데우는 것이 아니라 아무도 안 쓸 문장을 데우게 된다.
        audio_manager.set_line_catalog(
            lines.static_texts(), lines.session_templates()
        )
        prewarm_stats = await audio_manager.set_persona(persona, prewarm=prewarm)

    if broadcast is not None:
        try:
            await broadcast(catalog_message())
        except Exception:
            # 화면 갱신에 실패해도 음성은 새 페르소나로 나간다. 자막이 잠시
            # 옛 문장으로 남을 뿐이라 진행을 막지 않는다.
            logger.exception("페르소나 카탈로그 broadcast 실패")

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
