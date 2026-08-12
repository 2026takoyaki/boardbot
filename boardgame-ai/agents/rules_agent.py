"""규칙 에이전트 — 차례 위반·허용되지 않는 행동 감지 시 CRITICAL TTS 발화."""

from __future__ import annotations

from agents.base import BaseAgent, Intervention
from agents.context import AgentContext
from agents.tools import lines
from core.audio import AudioPriority
from core.events import GameEvent


class RulesAgent(BaseAgent):
    """우선순위 1 (CRITICAL). 규칙 위반이 감지되면 즉시 개입하고 하위 에이전트를 억제."""

    name = "rules"

    def on_game_event(self, event: GameEvent, ctx: AgentContext) -> Intervention | None:
        actor = event.actor_id

        # actor가 없거나 제한 목록 자체가 없으면 규칙 검사 불필요
        if not actor or not ctx.allowed_actors:
            return None

        # 허용되지 않은 액터 감지
        if actor not in ctx.allowed_actors:
            active_name = ctx.player_name(ctx.active_player)
            msg = (
                lines.render("rules.wrong_turn", player=active_name)
                if active_name
                else lines.get("rules.wrong_turn_unknown")
            )
            return Intervention(
                agent=self.name,
                tts_text=msg,
                priority=AudioPriority.CRITICAL,
                suppress_lower=True,
            )

        # 허용되지 않은 이벤트 타입 감지
        if ctx.expected_events and event.event_type not in ctx.expected_events:
            return Intervention(
                agent=self.name,
                tts_text=lines.get("rules.invalid_action"),
                priority=AudioPriority.CRITICAL,
                suppress_lower=True,
            )

        return None
