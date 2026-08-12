"""시스템이 발화하는 고정 멘트의 단일 소유자.

멘트가 여러 파일에 흩어져 있으면 페르소나를 적용할 수 없다. 말투를 바꾸려면
"바꿀 문장 목록"이 하나 있어야 하는데, 문장이 FSM 안에도 있고 프론트 컴포넌트
안에도 있으면 그 목록을 만들 수가 없다. 그래서 여기 한 곳에 모은다.

    LINES(고정 문장) --LLM 일괄 변환--> persona_lines/<페르소나>.json

변환은 런타임이 아니라 페르소나 선택 시점에 일괄로 한다. 발화할 때마다 LLM을
부르면 매 페이즈마다 생성+합성 지연이 겹쳐 진행이 끊긴다. 미리 변환해두고 TTS
캐시까지 채워두면 게임 중에는 캐시 hit만 남는다.

line_id 규칙: `<game_type>.<fsm_state>` 또는 `<agent>.<사건>`.
game_type/fsm_state는 AgentContext의 값을 그대로 쓴다 — 변환 테이블을 두면
그 테이블이 또 하나의 흩어진 소유자가 된다.

주의: 늑대인간 페이즈 멘트는 `audio/catalog.py`의 STATIC_LINES와 글자 단위로
같아야 부팅 시 prewarm한 TTS 캐시에 hit한다. 여기 문장을 고치면 그쪽도 같이
고칠 것. (tests/test_agent_lines.py가 감시한다)
"""

# 멘트는 코드가 아니라 데이터다. 줄바꿈으로 접으면 문자열 연결 과정에서 공백이
# 끼어들기 쉽고, 캐시 키가 텍스트 기반이라 공백 한 칸에 prewarm이 통째로 무효화된다.
# 한 줄 = 한 멘트를 유지한다.
# ruff: noqa: E501

from __future__ import annotations

import re

# ── 늑대인간: 일반 모드 ─────────────────────────────────────────────────────────
# 눈을 감고 진행하므로 "깨어나세요" 호명 방식.
_WEREWOLF: dict[str, str] = {
    "night_start":        "밤이 되었습니다. 모두 눈을 감아주세요.",
    "night_doppelganger": "도플갱어는 깨어나세요. 다른 플레이어 1명의 카드를 확인하세요. 그 역할이 됩니다.",
    "night_werewolf":     "늑대인간은 깨어나세요. 서로를 확인하고 다시 눈을 감으세요.",
    "night_minion":       "하수인은 깨어나세요. 늑대인간들은 엄지를 들어올려 자신을 알려주세요.",
    "night_mason":        "프리메이슨은 깨어나세요. 서로를 확인하고 다시 눈을 감으세요.",
    "night_seer":         "예언자는 깨어나세요. 다른 플레이어 1명 또는 중앙 카드 2장을 확인할 수 있습니다.",
    "night_robber":       "도둑은 깨어나세요. 다른 플레이어 1명의 카드와 자신의 카드를 교환할 수 있습니다.",
    "night_troublemaker": "말썽꾼은 깨어나세요. 자신을 제외한 두 플레이어의 카드를 서로 교환하세요.",
    "night_drunk":        "주정뱅이는 깨어나세요. 중앙 카드 1장을 가져와 자신의 카드와 교환하세요. 새 카드는 볼 수 없습니다.",
    "night_insomniac":    "불면증환자는 깨어나세요. 자신의 카드를 확인하세요.",
}

# ── 늑대인간: 튜토리얼 모드 ────────────────────────────────────────────────────
# 눈을 감지 않고 진행하므로 호명 대신 역할 설명 + 행동 안내.
# NightRoleAnnounce.jsx의 tutorialAnnounce/tutorialAction 문구와 일치시킨다.
_WEREWOLF_PRACTICE: dict[str, str] = {
    "night_start":        "밤이 되었습니다. 튜토리얼 모드에서는 눈을 감지 않고 역할 순서대로 행동을 진행합니다.",
    "night_doppelganger": "도플갱어는 기본적으로 마을주민팀이지만 팀이 바뀔 수 있는 역할입니다. 밤 시간에 다른 플레이어 1명의 카드를 확인하고 본인도 그 역할이 됩니다. 확인한 역할이 늑대인간이나 하수인이면 늑대인간팀, 무두장이면 무두장이팀으로 변경됩니다. 낮 시간에 바뀐 역할을 주장하며 혼란을 줄 수 있습니다.",
    "night_werewolf":     "늑대인간은 늑대인간팀 역할입니다. 밤 시간에 눈을 떠 다른 늑대인간들과 서로를 확인합니다. 낮 시간에 마을주민인 척 행동하며 다른 늑대인간들과 협력해 마을주민들을 처단하도록 유도합니다.",
    "night_minion":       "하수인은 늑대인간팀 역할입니다. 밤 시간에 늑대인간들이 엄지를 들면 눈을 떠 누가 늑대인간인지 확인합니다. 단, 늑대인간들은 하수인이 누구인지 모릅니다. 낮 시간에 늑대인간으로 의심받을 행동을 하여 늑대인간 대신 본인이 처단당하도록 유도합니다.",
    "night_mason":        "프리메이슨은 마을주민팀 역할입니다. 프리메이슨은 항상 두 명입니다. 밤 시간에 다른 프리메이슨과 눈을 마주치며 서로를 확인합니다. 낮 시간에 서로를 믿고 협력하며 함께 늑대인간을 찾아냅니다.",
    "night_seer":         "예언자는 마을주민팀 역할입니다. 밤 시간에 다른 플레이어 1명의 카드를 확인하거나, 중앙 카드 2장을 확인할 수 있습니다. 낮 시간에 본인이 확인한 정보를 바탕으로 마을주민들의 추리를 돕습니다.",
    "night_robber":       "강도는 마을주민팀 역할입니다. 밤 시간에 다른 플레이어 1명의 카드를 자신의 카드와 맞교환하고 바뀐 역할을 확인합니다. 단, 카드를 빼앗긴 플레이어는 이 사실을 모릅니다. 낮 시간에 바뀐 역할로 행동하며 역할을 빼앗긴 플레이어에게 혼란을 줍니다.",
    "night_troublemaker": "말썽쟁이는 마을주민팀 역할입니다. 밤 시간에 자신을 제외한 두 플레이어의 카드를 맞교환하며 두 플레이어의 역할은 확인하지 않습니다. 단, 역할이 맞교환된 두 플레이어는 이 사실을 모릅니다. 낮 시간에 플레이어들이 본인의 역할을 잘못 알고 행동하도록 합니다.",
    "night_drunk":        "주정뱅이는 마을주민팀 역할입니다. 밤 시간에 중앙 카드 1장과 자신의 카드를 교환하며 본인의 바뀐 역할은 확인하지 않습니다. 낮 시간에 자신이 어떤 역할인지 전혀 모른 채 추리에 참여해야 하는 역할입니다.",
    "night_insomniac":    "불면증환자는 마을주민팀 역할입니다. 밤 시간이 끝날 무렵 가장 마지막으로 자신의 카드를 확인합니다. 카드가 바뀌어 있다면 누군가 본인의 역할을 교환했다는 것을 알 수 있습니다. 낮 시간에 이 정보를 바탕으로 마을주민들의 추리를 돕습니다.",
}

# ── 규칙 위반 (RulesAgent, CRITICAL) ───────────────────────────────────────────
_RULES: dict[str, str] = {
    "wrong_turn":         "지금은 {player}님의 차례입니다.",
    "wrong_turn_unknown": "지금은 다른 플레이어의 차례입니다.",
    "invalid_action":     "지금은 해당 행동을 할 수 없습니다.",
}

# ── 턴 타이머 마일스톤 (TempoAgent, HIGH) ──────────────────────────────────────
_TEMPO: dict[str, str] = {
    "half":   "절반의 시간이 지났습니다.",
    "hurry":  "시간이 얼마 남지 않았습니다.",
    "almost": "시간이 거의 다 됐습니다!",
}


LINES: dict[str, str] = {
    **{f"werewolf.{k}": v for k, v in _WEREWOLF.items()},
    **{f"werewolf_practice.{k}": v for k, v in _WEREWOLF_PRACTICE.items()},
    **{f"rules.{k}": v for k, v in _RULES.items()},
    **{f"tempo.{k}": v for k, v in _TEMPO.items()},
}


def get(line_id: str) -> str | None:
    """line_id의 원문 템플릿. 없으면 None."""
    return LINES.get(line_id)


def render(line_id: str, **params: object) -> str | None:
    """line_id를 params로 채워 실제 발화 문장으로. 없는 line_id면 None.

    str.format을 쓰지 않는다 — 멘트에 중괄호가 섞여 있거나 params가 비면
    KeyError로 발화 자체가 죽는다. 채울 수 있는 슬롯만 채우고 나머지는 둔다.
    """
    template = LINES.get(line_id)
    if template is None:
        return None
    return fill(template, **params)


def fill(template: str, **params: object) -> str:
    """템플릿의 {key} 슬롯을 params로 치환. 값이 없는 슬롯은 빈 문자열로."""
    def _sub(match: re.Match[str]) -> str:
        value = params.get(match.group(1))
        return "" if value is None else str(value)

    return re.sub(r"\{(\w+)\}", _sub, template)
