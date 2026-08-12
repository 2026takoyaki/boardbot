"""진행 에이전트 — FSM 상태 전환마다 NORMAL 우선순위 TTS로 진행을 안내.

모든 TTS 발화는 FSM이 아닌 이 에이전트가 전담한다.
- 요트: FSM의 last_message를 읽어 매 굴림/상태마다 동적으로 발화.
- 늑대인간: 페이즈별 고정 스크립트를 사용하며, 중복 발화를 방지.

멘트 원문은 `agents/tools/lines.py`가 소유한다 — 페르소나가 말투를 바꾸려면 문장이
한 곳에 모여 있어야 한다. 여기는 "언제 어떤 line_id를 발화할지"만 결정한다.

line_id는 `<game_type>.<fsm_state>`로 그대로 조립한다. 매핑 테이블을 따로 두면
그 테이블이 또 하나의 문장 소유자가 되어 모아둔 의미가 없어진다.

vote_countdown/final_role_reveal/result는 FUSION_CONTEXT를 emit하지 않으므로 제외.
day_discussion은 NightEnd 컴포넌트가 "아침이 밝았습니다 → 토론 시작" 순서를
관리하므로 여기서 발화하면 순서가 충돌한다.

LLM은 안내를 만들지 않는다. 안내는 매 상태 전환마다 나가는 말이라 캐시에서
즉시 나와야 하고, 생성에 실패하면 진행이 끊긴다. LLM이 붙는 자리는 안내
'뒤에' 덧붙는 상황 한마디(reaction)뿐이다 — 이건 늦어도 되고, 못 나오면
그냥 안 나온다. 이미 할 말은 안내가 다 했기 때문이다.
"""

from __future__ import annotations

from typing import Any

from agents.base import BaseAgent, Intervention
from agents.context import AgentContext
from agents.tools import lines, llm
from core.audio import AudioPriority

# 한마디 덧붙일 자리. 매 굴림마다 코멘트를 달면 진행자가 수다스러워서 게임이
# 굴러가지 않는다. 점수가 확정되는 순간에만 반응한다.
_REACTION_LINE_IDS = frozenset({"yacht.score_recorded", "yacht.game_finish"})

# 이 점수 아래로는 침묵한다. 4점짜리마다 감탄하면 요트가 터졌을 때 할 말이 없다.
_REACTION_MIN_SCORE = 20

_REACTION_MAX_TOKENS = 80


class ProgressAgent(BaseAgent):
    """우선순위 3 (NORMAL). 페이즈 전환마다 진행 내러티브를 안내한다."""

    name = "progress"

    def __init__(self) -> None:
        self._last_state: str = ""
        self._last_reaction: str = ""

    def on_state_change(self, ctx: AgentContext) -> Intervention | None:
        if ctx.game_type == "yacht":
            return self._yacht_progress(ctx)
        return self._werewolf_progress(ctx)

    def _yacht_progress(self, ctx: AgentContext) -> Intervention | None:
        if ctx.game_specific.get("tutorial_mode") and ctx.fsm_state != "AWAITING_ROLL":
            return None
        # 요트는 같은 fsm_state(awaiting_keep 등)가 매 굴림마다 반복되므로
        # 상태명 중복 체크를 하지 않는다 — 굴릴 때마다 새로 안내해야 한다.
        text = self._render(ctx.game_specific)
        if not text:
            return None
        return Intervention(
            agent=self.name,
            tts_text=text,
            priority=AudioPriority.NORMAL,
            suppress_lower=False,
        )

    @staticmethod
    def _render(game_specific: dict[str, Any]) -> str:
        """발화 지시(narration)를 문장으로. 지시가 없으면 last_message로 폴백.

        폴백은 아직 narration으로 옮기지 않은 경로를 위한 것이다. 전부 옮기고
        나면 지울 것 — 문장이 두 경로로 들어오면 페르소나가 한쪽을 놓친다.
        """
        narration = game_specific.get("narration")
        if narration:
            rendered = lines.render(
                str(narration.get("line_id", "")), **narration.get("params", {})
            )
            if rendered:
                return rendered
        return game_specific.get("last_message") or ""

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

    # ── 상황 한마디 (LLM, 백그라운드) ──────────────────────────────────────────
    # 안내가 나간 뒤에 덧붙는다. 안내는 이미 캐시로 즉시 나갔으므로 이 한마디가
    # 2~3초 늦어도 침묵이 생기지 않는다. 실패하면 그냥 안 붙는다.

    async def reaction(self, ctx: AgentContext) -> Intervention | None:
        """방금 벌어진 일에 대한 짧은 반응. 반응할 순간이 아니면 None."""
        moment = self._reaction_moment(ctx)
        if moment is None:
            return None
        line_id, params = moment

        # 같은 굴림에 두 번 반응하지 않는다. 상태 전환이 여러 번 통지될 수 있다.
        key = f"{line_id}:{params.get('scorer')}:{params.get('label')}:{params.get('score')}"
        if key == self._last_reaction:
            return None
        self._last_reaction = key

        finished = line_id == "yacht.game_finish"
        result = await llm.get_client().complete(
            llm.persona_style()
            + "당신은 요트다이스 진행자입니다. 방금 나온 결과에 한 문장으로 짧게 "
            "반응하세요. 다음 차례 안내는 이미 했으니 하지 마세요. "
            "점수와 이름은 주어진 값만 쓰고 새로 만들지 마세요.",
            "{who}님이 {label}에 {score}점을 넣었습니다.{tail}".format(
                who=params.get("scorer", ""),
                label=params.get("label", ""),
                score=params.get("score", 0),
                tail=" 이걸로 게임이 끝났습니다." if finished else "",
            ),
            max_tokens=_REACTION_MAX_TOKENS,
            tag="progress.reaction",
        )
        if not result.text:
            return None
        return Intervention(
            agent=self.name,
            tts_text=result.text,
            priority=AudioPriority.NORMAL,
            suppress_lower=False,
        )

    @staticmethod
    def _reaction_moment(ctx: AgentContext) -> tuple[str, dict[str, Any]] | None:
        """반응할 만한 순간인가. 아니면 None."""
        narration = ctx.game_specific.get("narration")
        if not isinstance(narration, dict):
            return None
        line_id = str(narration.get("line_id", ""))
        if line_id not in _REACTION_LINE_IDS:
            return None
        params = narration.get("params") or {}
        if not isinstance(params, dict):
            return None
        try:
            score = int(params.get("score", 0))
        except (TypeError, ValueError):
            return None
        # 게임이 끝나는 순간은 점수와 무관하게 한마디 할 값어치가 있다.
        if line_id != "yacht.game_finish" and score < _REACTION_MIN_SCORE:
            return None
        return line_id, params

    def reset(self) -> None:
        """새 판 시작 시. 앞 판의 마지막 순간에 다시 반응하지 않도록."""
        self._last_state = ""
        self._last_reaction = ""
