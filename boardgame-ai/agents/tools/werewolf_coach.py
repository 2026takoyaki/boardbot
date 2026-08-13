"""늑대인간 역할별 전략 판단.

요트에 yacht_coach가 있는데 늑대인간에는 없어서, 같은 성격의 판단이
StrategyAgent 안에 하드코딩으로 남아 있었다. 문장이 에이전트에 박혀 있으면
페르소나가 닿지 않는다.

여기서는 **문장을 만들지 않는다.** 어떤 조언을 할지(line_id)만 정하고
문장은 agents/tools/lines.py가 소유한다.

요트 코치와 달리 상태를 보지 않는다 — 시스템은 누가 어떤 역할인지 모르고
(카드를 보지 않는다), 지금 깨어난 역할이 무엇인지만 안다. 그래서 조언도
"이 역할은 이렇게 움직이면 좋다" 수준에서 멈춘다.
"""

from __future__ import annotations

# 야간 페이즈 중 조언할 것이 있는 역할. 늑대인간·하수인·프리메이슨은 서로
# 확인만 하면 끝이라 따로 조언할 것이 없다.
PHASE_TIPS: dict[str, str] = {
    "night_doppelganger": "strategy.ww_doppelganger",
    "night_seer":         "strategy.ww_seer",
    "night_robber":       "strategy.ww_robber",
    "night_troublemaker": "strategy.ww_troublemaker",
    "night_drunk":        "strategy.ww_drunk",
    "night_insomniac":    "strategy.ww_insomniac",
}

# LLM에 "지금 어떤 역할 차례인지" 알려줄 때 쓰는 한글 이름.
# 발화용이 아니라 프롬프트 재료다.
PHASE_KO: dict[str, str] = {
    "night_doppelganger": "도플갱어",
    "night_seer":         "예언자",
    "night_robber":       "도둑",
    "night_troublemaker": "말썽꾼",
    "night_drunk":        "주정뱅이",
    "night_insomniac":    "불면증 환자",
}

STRATEGY_PHASES = frozenset(PHASE_TIPS)


def advise(fsm_state: str) -> str | None:
    """이 페이즈에서 할 조언의 line_id. 조언할 것이 없으면 None."""
    return PHASE_TIPS.get(fsm_state)


def phase_name(fsm_state: str) -> str:
    """프롬프트에 넣을 역할 이름. 모르는 페이즈면 상태명 그대로."""
    return PHASE_KO.get(fsm_state, fsm_state)
