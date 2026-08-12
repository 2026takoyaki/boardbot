"""진행 에이전트 — FSM 상태 전환마다 NORMAL 우선순위 TTS로 진행을 안내.

모든 TTS 발화는 FSM이 아닌 이 에이전트가 전담한다.
- 요트: FSM의 last_message를 읽어 매 굴림/상태마다 동적으로 발화.
- 늑대인간: 페이즈별 고정 스크립트를 사용하며, 중복 발화를 방지.

멘트 원문은 `agents/lines.py`가 소유한다 — 페르소나가 말투를 바꾸려면 문장이
한 곳에 모여 있어야 한다. 여기는 "언제 어떤 line_id를 발화할지"만 결정한다.

line_id는 `<game_type>.<fsm_state>`로 그대로 조립한다. 매핑 테이블을 따로 두면
그 테이블이 또 하나의 문장 소유자가 되어 모아둔 의미가 없어진다.

vote_countdown/final_role_reveal/result는 FUSION_CONTEXT를 emit하지 않으므로 제외.
day_discussion은 NightEnd 컴포넌트가 "아침이 밝았습니다 → 토론 시작" 순서를
관리하므로 여기서 발화하면 순서가 충돌한다.
"""

from __future__ import annotations

from agents import lines
from agents.base import BaseAgent, Intervention
from agents.context import AgentContext
from core.audio import AudioPriority


class ProgressAgent(BaseAgent):
    """우선순위 3 (NORMAL). 페이즈 전환마다 진행 내러티브를 안내한다."""

    name = "progress"

    def __init__(self) -> None:
        self._last_state: str = ""

    def on_state_change(self, ctx: AgentContext) -> Intervention | None:
        if ctx.game_type == "yacht":
            return self._yacht_progress(ctx)
        return self._werewolf_progress(ctx)

    def _yacht_progress(self, ctx: AgentContext) -> Intervention | None:
        if ctx.game_specific.get("tutorial_mode") and ctx.fsm_state != "AWAITING_ROLL":
            return None
        # 요트는 같은 fsm_state(awaiting_keep 등)가 매 굴림마다 반복되므로
        # 상태명 중복 체크 대신 last_message 내용으로 TTS 발화를 결정한다.
        text = ctx.game_specific.get("last_message", "")
        if not text:
            return None
        return Intervention(
            agent=self.name,
            tts_text=text,
            priority=AudioPriority.NORMAL,
            suppress_lower=False,
        )

    def _werewolf_progress(self, ctx: AgentContext) -> Intervention | None:
        # 같은 상태로 중복 호출 방지 (늑대인간 페이즈는 게임 내 반복되지 않음)
        if ctx.fsm_state == self._last_state:
            return None
        self._last_state = ctx.fsm_state

        text = lines.render(
            f"{ctx.game_type}.{ctx.fsm_state}",
            player=ctx.player_name(ctx.active_player) or "",
        )
        if not text:
            return None

        return Intervention(
            agent=self.name,
            tts_text=text,
            priority=AudioPriority.NORMAL,
            suppress_lower=False,  # 전략 에이전트와 공존 가능
        )
