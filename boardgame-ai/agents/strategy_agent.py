"""전략 에이전트 — 활성화 시 의사결정 시점에 전략 추천을 제공.

GPT(gpt-5.4-mini) 호출로 동적 전략을 생성하고, 실패 시 규칙 기반 팁으로 폴백한다.
OPENAI_API_KEY 환경변수가 없으면 규칙 기반 모드로만 동작.

set_enabled(True) 호출 시 활성화. 기본은 비활성.
game_specific에서 필요한 정보를 읽는다.
  - 요트: {"dice_values": [1,2,3,4,5], "available_categories": [...], "roll_count": N}
  - 늑대인간: fsm_state로 역할 페이즈 판별
"""

from __future__ import annotations

import asyncio
import logging
import os

from agents.base import BaseAgent, Intervention
from agents.context import AgentContext
from agents.tools import lines, yacht_coach
from core.audio import AudioPriority

logger = logging.getLogger(__name__)

# ── 요트다이스: 카테고리 한글명 ──────────────────────────────────────────────────
_CATEGORY_KO: dict[str, str] = {
    "ones":           "1점짜리",
    "twos":           "2점짜리",
    "threes":         "3점짜리",
    "fours":          "4점짜리",
    "fives":          "5점짜리",
    "sixes":          "6점짜리",
    "choice":         "찬스",
    "four_of_a_kind": "포카인드",
    "full_house":     "풀하우스",
    "small_straight": "스몰스트레이트",
    "large_straight": "라지스트레이트",
    "yacht":          "요트",
}

# ── 늑대인간: 페이즈 한글명 ──────────────────────────────────────────────────────
_WEREWOLF_PHASE_KO: dict[str, str] = {
    "night_doppelganger": "도플갱어",
    "night_seer":         "예언자",
    "night_robber":       "도둑",
    "night_troublemaker": "말썽꾼",
    "night_drunk":        "주정뱅이",
    "night_insomniac":    "불면증 환자",
}

# ── 늑대인간: 규칙 기반 폴백 팁 ─────────────────────────────────────────────────
_WEREWOLF_PHASE_TIPS: dict[str, str] = {
    "night_doppelganger": (
        "도플갱어는 다른 플레이어의 카드를 몰래 확인해 그 역할을 복사합니다. "
        "강력한 역할(예언자, 도둑)을 노리세요."
    ),
    "night_seer": (
        "예언자는 다른 플레이어 카드 한 장 또는 센터 카드 두 장을 볼 수 있습니다. "
        "의심스러운 플레이어의 카드를 확인하는 것이 효과적입니다."
    ),
    "night_robber": (
        "도둑은 다른 플레이어와 카드를 교환할 수 있습니다. "
        "강력한 역할을 가진 플레이어의 카드를 노리세요."
    ),
    "night_troublemaker": (
        "말썽꾼은 두 플레이어의 카드를 교환합니다. "
        "늑대인간으로 의심되는 플레이어와 다른 플레이어의 카드를 바꿔 혼란을 주세요."
    ),
    "night_drunk": (
        "주정뱅이는 센터 카드 중 하나와 자신의 카드를 교환합니다. "
        "자신의 새 역할을 알 수 없으니 낮 토론에서 신중하게 행동하세요."
    ),
    "night_insomniac": (
        "불면증 환자는 밤이 끝난 후 자신의 최종 카드를 확인합니다. "
        "카드가 바뀌었다면 누군가 손을 댔다는 단서가 됩니다."
    ),
}

_YACHT_STRATEGY_PHASES = frozenset({"AWAITING_KEEP", "AWAITING_SCORE"})
_WEREWOLF_STRATEGY_PHASES = frozenset(_WEREWOLF_PHASE_TIPS.keys())

_LLM_TIMEOUT = 5.0   # 초 — 초과 시 규칙 기반 폴백
_LLM_MAX_TOKENS = 80


def _get_openai_client():
    """OPENAI_API_KEY가 있으면 AsyncOpenAI 클라이언트 반환, 없으면 None."""
    try:
        from openai import AsyncOpenAI
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            return None
        return AsyncOpenAI(api_key=api_key)
    except ImportError:
        return None


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

        client = _get_openai_client()
        if client is not None:
            try:
                text = await asyncio.wait_for(
                    self._llm_advice(ctx, client), timeout=_LLM_TIMEOUT
                )
                if text:
                    return Intervention(
                        agent=self.name,
                        tts_text=text,
                        priority=AudioPriority.LOW,
                        suppress_lower=False,
                    )
            except asyncio.TimeoutError:
                logger.warning("[StrategyAgent] LLM 타임아웃 — 규칙 기반 폴백")
            except Exception:
                logger.exception("[StrategyAgent] LLM 호출 실패 — 규칙 기반 폴백")

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

        return self._coach_intervention(fragments, transient=advice.transient)

    def _coach_intervention(
        self,
        fragments: list[tuple[str, dict[str, object]]],
        transient: bool,
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

    async def _llm_advice(self, ctx: AgentContext, client) -> str | None:
        if ctx.game_type == "yacht":
            return await self._llm_yacht(ctx, client)
        if ctx.game_type == "werewolf":
            return await self._llm_werewolf(ctx, client)
        return None

    async def _llm_yacht(self, ctx: AgentContext, client) -> str | None:
        gs = ctx.game_specific
        dice: list = gs.get("dice_values", [])
        available: list = gs.get("available_categories", [])
        roll_count: int = gs.get("roll_count", 0)

        if ctx.fsm_state not in _YACHT_STRATEGY_PHASES or not dice or not available:
            return None
        if any(v is None for v in dice):
            return None

        dice_str = ", ".join(str(d) for d in dice)
        cats_str = ", ".join(_CATEGORY_KO.get(c, c) for c in available)

        resp = await client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 요트다이스 게임 전략가입니다. "
                        "현재 상황에서 최선의 카테고리와 이유를 1~2문장으로 한국어로 간결하게 설명하세요. "
                        "불필요한 설명 없이 핵심만 말하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"주사위: {dice_str} ({roll_count}/3번 굴림)\n"
                        f"선택 가능한 카테고리: {cats_str}"
                    ),
                },
            ],
            max_tokens=_LLM_MAX_TOKENS,
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()

    async def _llm_werewolf(self, ctx: AgentContext, client) -> str | None:
        if ctx.fsm_state not in _WEREWOLF_STRATEGY_PHASES:
            return None

        phase_ko = _WEREWOLF_PHASE_KO.get(ctx.fsm_state, ctx.fsm_state)

        resp = await client.chat.completions.create(
            model="gpt-5.4-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "당신은 한밤의 늑대인간 보드게임 전략가입니다. "
                        "역할별 야간 행동 전략을 1~2문장으로 한국어로 간결하게 설명하세요."
                    ),
                },
                {
                    "role": "user",
                    "content": f"현재 깨어난 역할: {phase_ko}",
                },
            ],
            max_tokens=_LLM_MAX_TOKENS,
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()

    # ── 규칙 기반 내부 메서드 ──────────────────────────────────────────────────

    def _yacht_strategy(self, ctx: AgentContext) -> Intervention | None:
        if ctx.fsm_state not in _YACHT_STRATEGY_PHASES:
            return None
        gs = ctx.game_specific
        dice: list[int | None] = gs.get("dice_values", [])
        available: list[str] = gs.get("available_categories", [])
        if not dice or not available:
            return None
        text = self._best_category_tip(dice, available)
        if not text:
            return None
        return Intervention(
            agent=self.name,
            tts_text=text,
            priority=AudioPriority.LOW,
            suppress_lower=False,
        )

    def _best_category_tip(self, dice: list[int | None], available: list[str]) -> str | None:
        try:
            from games.yacht.scoring import calculate_score
        except ImportError:
            return None
        if any(v is None for v in dice):
            return None
        scores: list[tuple[int, str]] = []
        for cat in available:
            try:
                scores.append((calculate_score(cat, dice), cat))
            except Exception:
                continue
        if not scores:
            return None
        scores.sort(key=lambda x: x[0], reverse=True)
        best_score, best_cat = scores[0]
        cat_ko = _CATEGORY_KO.get(best_cat, best_cat)
        if best_score == 0:
            return "현재 주사위로 점수가 나오는 카테고리가 없습니다. 낮은 값을 가진 카테고리에 0을 기록하는 것을 추천합니다."
        return f"현재 주사위 조합에서는 {cat_ko}에 기록하면 {best_score}점을 얻을 수 있습니다."

    def _werewolf_strategy(self, ctx: AgentContext) -> Intervention | None:
        if ctx.fsm_state not in _WEREWOLF_STRATEGY_PHASES:
            return None
        tip = _WEREWOLF_PHASE_TIPS.get(ctx.fsm_state)
        if not tip:
            return None
        return Intervention(
            agent=self.name,
            tts_text=tip,
            priority=AudioPriority.LOW,
            suppress_lower=False,
        )
