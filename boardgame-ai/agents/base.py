"""에이전트 베이스 클래스 및 Intervention 타입."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass

from core.audio import AudioPriority
from core.events import GameEvent

from agents.context import AgentContext


@dataclass
class Intervention:
    """에이전트가 반환하는 개입 결과."""

    agent: str
    tts_text: str | None
    priority: AudioPriority
    suppress_lower: bool = True  # True면 하위 우선순위 에이전트를 이번 이벤트에서 건너뜀
    # 화면에도 띄울 것인가. 듣고 흘리면 그만인 안내와, 눈으로 확인하며 따라야
    # 하는 조언은 다르다 — 튜토리얼 코치는 후자다.
    display: bool = False
    # 화면에서 잠시 후 사라져야 하는지. 지금 테이블에 놓인 눈에 대한 말은
    # 눈이 그대로인 동안 남아 있어야 한다.
    transient: bool = False
    # 어떤 말투로 말할지. None이면 그 에이전트의 기본 말투.
    # 목소리는 바뀌지 않는다 — 같은 사람이 톤을 올리는 것뿐이다.
    # 요트 대박이 터졌는데 진행 안내와 같은 톤으로 읽으면 김이 샌다.
    delivery: str | None = None


class BaseAgent(ABC):
    name: str = "base"

    def on_state_change(self, ctx: AgentContext) -> Intervention | None:
        return None

    def on_game_event(self, event: GameEvent, ctx: AgentContext) -> Intervention | None:
        return None
