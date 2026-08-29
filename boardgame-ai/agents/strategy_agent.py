"""전략 에이전트 — 활성화 시 의사결정 시점에 전략 추천을 제공.

GPT(gpt-5.4-mini) 호출로 동적 전략을 생성하고, 실패 시 규칙 기반 팁으로 폴백한다.
OPENAI_API_KEY 환경변수가 없으면 규칙 기반 모드로만 동작.

set_enabled(True) 호출 시 활성화. 기본은 비활성.
game_specific에서 필요한 정보를 읽는다.
  - 요트: {"dice_values": [1,2,3,4,5], "available_categories": [...], "roll_count": N}
  - 늑대인간: fsm_state로 역할 페이즈 판별
"""

from __future__ import annotations

import logging

from agents.base import BaseAgent, Intervention
from agents.context import AgentContext
from agents.tools import lines, llm, werewolf_coach, yacht_coach
from core.audio import AudioPriority
from core.persona import DELIVERY_EXCITED

logger = logging.getLogger(__name__)

# 문장은 tools/lines.py, 판단은 tools/yacht_coach.py·werewolf_coach.py가 소유한다.
# 여기는 "지금 훈수를 둘 때인가"만 정한다.
_YACHT_STRATEGY_PHASES = frozenset({"AWAITING_KEEP", "AWAITING_SCORE"})
_WEREWOLF_STRATEGY_PHASES = werewolf_coach.STRATEGY_PHASES

_LLM_MAX_TOKENS = 120

# 야간 조언은 여기서 따로 자른다.
#
# 요트의 조언은 플레이어가 점수판을 보며 고민하는 동안 나가므로 길어도 된다.
# 늑대인간 야간은 단계가 몇 초짜리라 사정이 다르다 — 안내가 5초, 마지막
# "눈을 다시 감아주세요"에 4초를 쓰고 나면 조언에 남는 것은 5초 남짓이다.
# 프롬프트로 "짧게"라고 부탁하는 것만으로는 지켜지지 않으므로 상한으로 막는다.
_WEREWOLF_NIGHT_MAX_TOKENS = 40


class StrategyAgent(BaseAgent):
    """우선순위 4 (LOW). 활성화 시 의사결정 시점에 전략 추천을 안내한다.

    LLM(gpt-5.4-mini) → 타임아웃/실패 시 규칙 기반 폴백 순으로 동작.
    """

    name = "strategy"

    def __init__(self) -> None:
        self._enabled: bool = False
        self._last_coach_key: str | None = None
        self._seen_coach_hints: set[str] = set()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = enabled

    @property
    def enabled(self) -> bool:
        return self._enabled

    def reset_coach(self) -> None:
        """새 판 시작 시 호출. 앞 판에서 이미 설명한 것을 다시 설명하지 않도록
        기억을 비운다."""
        self._last_coach_key = None
        self._seen_coach_hints.clear()

    # ── 오케스트레이터가 호출하는 async 진입점 ────────────────────────────────────

    async def on_state_change_async(self, ctx: AgentContext) -> Intervention | None:
        """튜토리얼이면 코치, 아니면 전략 코칭(토글 시)."""
        # 튜토리얼 코치는 토글과 무관하게 항상 켜진다 — 처음 하는 사람에게
        # "조언 켜기"를 먼저 찾게 하는 것은 순서가 뒤집힌 요구다.
        if ctx.game_type == "yacht" and ctx.game_specific.get("tutorial_mode"):
            return self._tutorial_coach(ctx)

        if not self._enabled:
            return None

        # LLM이 되면 그 말을 쓰고, 안 되면 규칙 기반으로 떨어진다.
        # 실패 사유는 llm.get_client().stats()에 남는다 — 조용히 폴백하면
        # 왜 LLM이 안 붙는지 알 방법이 없다.
        text = await self._llm_advice(ctx)
        if text:
            return Intervention(
                agent=self.name,
                tts_text=text,
                priority=AudioPriority.LOW,
                suppress_lower=False,
            )
        return self.on_state_change(ctx)

    # ── 튜토리얼 코치 ─────────────────────────────────────────────────────────
    # 조언 판단은 agents/tools/yacht_coach.py, 문장은 agents/tools/lines.py가 소유한다.
    # 여기는 "지금 말할 때인가"만 정한다.

    def _tutorial_coach(self, ctx: AgentContext) -> Intervention | None:
        gs = ctx.game_specific
        dice = [v for v in gs.get("dice_values", []) if v is not None]
        key = yacht_coach.advice_key(
            ctx.fsm_state, ctx.active_player, int(gs.get("roll_count", 0)), dice
        )
        if key == self._last_coach_key:
            return None
        self._last_coach_key = key

        # 굴리기 전 안내는 조작법이라 처음 한 번이면 된다. 두 번째 사람부터는
        # 침묵해야 앞사람 굴림에 대한 조언이 화면에 남아 있지 않는다.
        if key is None or key == "roll":
            if key != "roll" or "roll" in self._seen_coach_hints:
                return self._clear_coach()
            self._seen_coach_hints.add("roll")
            return self._coach_intervention(
                [("coach.first_roll", {})], transient=True
            )

        advice = yacht_coach.advise(
            dice,
            list(gs.get("available_categories", [])),
            int(gs.get("roll_count", 0)),
        )
        if advice is None:
            return self._clear_coach()

        # 처음 굴린 사람에게만 "어떻게 다시 굴리는가"를 앞에 붙인다. 조언 자체는
        # 매번 다르므로 반복으로 느껴지지 않지만, 조작법은 한 번이면 족하다.
        fragments = list(advice.fragments)
        if "reroll" not in self._seen_coach_hints:
            self._seen_coach_hints.add("reroll")
            fragments.insert(0, ("coach.reroll_mechanic", {}))

        return self._coach_intervention(
            fragments, transient=advice.transient, excited=advice.excited
        )

    def _coach_intervention(
        self,
        fragments: list[tuple[str, dict[str, object]]],
        transient: bool,
        excited: bool = False,
    ) -> Intervention | None:
        parts = [lines.render(line_id, **params) for line_id, params in fragments]
        text = " ".join(p for p in parts if p)
        if not text:
            return None
        return Intervention(
            agent=self.name,
            tts_text=text,
            priority=AudioPriority.LOW,
            suppress_lower=False,
            display=True,
            transient=transient,
            delivery=DELIVERY_EXCITED if excited else None,
        )

    def _clear_coach(self) -> Intervention:
        """화면의 코치 문구를 지운다. 발화는 하지 않는다."""
        return Intervention(
            agent=self.name,
            tts_text=None,
            priority=AudioPriority.LOW,
            suppress_lower=False,
            display=True,
        )

    # ── 규칙 기반 (동기, LLM 폴백 및 직접 호출용) ────────────────────────────────

    def on_state_change(self, ctx: AgentContext) -> Intervention | None:
        if not self._enabled:
            return None
        if ctx.game_type == "yacht":
            return self._yacht_strategy(ctx)
        if ctx.game_type == "werewolf":
            return self._werewolf_strategy(ctx)
        return None

    # ── LLM 호출 ──────────────────────────────────────────────────────────────
    # 전략 조언은 지연이 허용되는 유일한 자리다. 플레이어가 점수판을 보며
    # 고민하는 동안 나오므로 2~3초 늦어도 아무도 기다리지 않는다. 그래서
    # 네 에이전트 중 유일하게 그 자리에서 직접 부른다.

    async def _llm_advice(self, ctx: AgentContext) -> str | None:
        if ctx.game_type == "yacht":
            return await self._llm_yacht(ctx)
        if ctx.game_type == "werewolf":
            return await self._llm_werewolf(ctx)
        return None

    async def _llm_yacht(self, ctx: AgentContext) -> str | None:
        gs = ctx.game_specific
        dice = list(gs.get("dice_values", []))
        available = list(gs.get("available_categories", []))

        if ctx.fsm_state not in _YACHT_STRATEGY_PHASES or not dice or not available:
            return None
        if any(v is None for v in dice):
            return None

        # 점수 계산은 LLM에게 시키지 않는다. 틀린 점수를 말하면 조언이 아니라
        # 거짓말이 된다. 계산은 도구가 하고 LLM은 그걸 말로 옮기기만 한다.
        best = yacht_coach.best_category(dice, available)
        hint = ""
        if best is not None:
            label = yacht_coach.KOREAN_LABEL.get(best[0], best[0])
            hint = f"\n지금 눈으로 가장 높은 칸: {label} {best[1]}점"

        result = await llm.get_client().complete(
            llm.persona_style()
            + "당신은 요트다이스 진행자입니다. "
            "지금 눈으로 어디에 넣으면 좋을지 한두 문장으로 짧게 말하세요. "
            "숫자는 주어진 값을 그대로 쓰고 새로 계산하지 마세요.",
            "주사위: {dice} ({rolls}/3번 굴림)\n남은 칸: {cats}{hint}".format(
                dice=", ".join(str(d) for d in dice),
                rolls=gs.get("roll_count", 0),
                cats=", ".join(yacht_coach.KOREAN_LABEL.get(c, c) for c in available),
                hint=hint,
            ),
            max_tokens=_LLM_MAX_TOKENS,
            tag="strategy.yacht",
        )
        return result.text

    async def _llm_werewolf(self, ctx: AgentContext) -> str | None:
        if ctx.fsm_state not in _WEREWOLF_STRATEGY_PHASES:
            return None

        result = await llm.get_client().complete(
            llm.persona_style()
            + "당신은 한밤의 늑대인간 진행자입니다. "
            "지금 깨어난 역할이 무엇을 노리면 좋을지 **25자 이내 한 문장**으로 말하세요. "
            "역할이 무엇을 할 수 있는지는 방금 안내가 이미 말했습니다. "
            "그 설명을 되풀이하지 말고 조언만 하세요. "
            "특정 플레이어를 지목하지 마세요 — 시스템은 누가 어떤 역할인지 모릅니다.",
            f"지금 깨어난 역할: {werewolf_coach.phase_name(ctx.fsm_state)}",
            max_tokens=_WEREWOLF_NIGHT_MAX_TOKENS,
            tag="strategy.werewolf",
        )
        return result.text

    # ── 규칙 기반 내부 메서드 ──────────────────────────────────────────────────

    def _yacht_strategy(self, ctx: AgentContext) -> Intervention | None:
        if ctx.fsm_state not in _YACHT_STRATEGY_PHASES:
            return None
        gs = ctx.game_specific
        best = yacht_coach.best_category(
            list(gs.get("dice_values", [])), list(gs.get("available_categories", []))
        )
        if best is None:
            return None
        category, score = best
        # 0점이면 "여기 넣으세요"가 아니라 "버릴 칸을 고르세요"가 된다.
        if score == 0:
            return self._tip("strategy.yacht_none")
        return self._tip(
            "strategy.yacht_best",
            label=yacht_coach.KOREAN_LABEL.get(category, category),
            score=score,
        )

    def _werewolf_strategy(self, ctx: AgentContext) -> Intervention | None:
        line_id = werewolf_coach.advise(ctx.fsm_state)
        return self._tip(line_id) if line_id else None

    def _tip(self, line_id: str, **params: object) -> Intervention | None:
        text = lines.render(line_id, **params)
        if not text:
            return None
        return Intervention(
            agent=self.name,
            tts_text=text,
            priority=AudioPriority.LOW,
            suppress_lower=False,
        )
