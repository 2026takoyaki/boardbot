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

import json
import re
from pathlib import Path

from agents.tools.line_validator import validate_all

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
    # 카드 세팅 안내. 프론트가 화면에 타이핑으로 그리면서 같은 문장을 발화한다.
    "setup_intro":       "이번 게임에 사용할 역할 카드입니다.",
    "setup_flip":        "모든 카드를 역할이 보이지 않게 뒤집어주세요.",
    "setup_take":        "각자 카드를 한 장씩 가져가고, 본인만 확인해주세요.",
    "setup_place":       "본인의 카드는 각자 자기 앞에 엎어서 놓아주세요.",
    "setup_center":      "나머지 카드는 역할이 보이지 않게 뒤집어 중앙에 놓아주세요.",
    "setup_close_eyes":  "모두 눈을 감아주세요.",
    "setup_confirm":     "모든 준비가 완료 되었으면 OK 싸인을 해주세요.",
    "role_select_prompt": "이번 게임에 사용할 카드 {count}장을 선택해주세요. 선택한 카드만 테이블에 올려두고 나머지 카드는 정리해주세요.",
    # 낮 전환·투표·종료.
    # 아침 안내는 화면이 큰 제목 + 작은 부제로 나눠 보여주므로 두 줄로 쪼개 둔다.
    # 한 문자열로 두면 화면이 쪼갤 방법이 없어 결국 프론트가 사본을 갖게 된다.
    # 발화는 두 줄을 이어서 한다.
    "morning":           "아침이 밝았습니다.",
    "morning_open_eyes": "모두 눈을 뜨세요.",
    "discussion_start":  "자, 지금부터 토론을 시작합니다. 늑대인간을 찾아내세요.",
    "vote_intro":        "투표를 시작하겠습니다. 카운트다운이 시작되면 플레이어를 지목해주세요.",
    "game_end":          "{headline}. 이제 각자 자신의 카드를 공개해 주세요. 승패는 여러분이 직접 확인하시면 됩니다.",
    # 카운트다운 호령. 숫자를 그대로 읽으면 "５"처럼 어색해서 한글로 둔다.
    "vote_count_5":      "오",
    "vote_count_4":      "사",
    "vote_count_3":      "삼",
    "vote_count_2":      "이",
    "vote_count_1":      "일",
    "vote_count_0":      "지목",
}

# ── 늑대인간: 튜토리얼 모드 (일반 모드를 상속하고 다른 것만 덮어쓴다) ─────────
# 눈을 감지 않고 진행하므로 호명 대신 역할 설명 + 행동 안내.
# NightRoleAnnounce.jsx의 tutorialAnnounce/tutorialAction 문구와 일치시킨다.
# 투표·확인 안내처럼 두 모드가 같은 문장은 여기 적지 않는다 — 적으면 한쪽만
# 고쳐놓고 다른 쪽이 옛 문장으로 남는 사고가 난다.
_WEREWOLF_PRACTICE_OVERRIDES: dict[str, str] = {
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
    # 카드 세팅 — 역할을 숨기지 않으므로 일반 모드와 문구가 갈린다.
    "setup_intro":       "이번 게임에 사용할 역할 카드입니다.",
    "setup_flip":        "모든 카드를 역할이 보이지 않게 뒤집어주세요.",
    "setup_take":        "각자 카드를 한 장씩 가져가주세요.",
    "setup_no_hide":     "튜토리얼 모드이므로 역할을 숨기지 않고 진행합니다.",
    "setup_place":       "본인의 카드는 각자 자기 앞에 놓아주세요.",
    "setup_center":      "나머지 카드는 역할이 보이도록 중앙에 놓아주세요.",
    "setup_close_eyes":  "튜토리얼 모드에서는 눈을 감지 않고 진행하겠습니다.",
    # 튜토리얼은 눈을 감지 않았으므로 "눈을 뜨세요"가 없다. 화면도 부제를 숨긴다.
    "morning_open_eyes": "",
    # 낮 규칙 설명. 튜토리얼은 토론을 건너뛰고 바로 투표로 가므로 여기서 한 번에 설명한다.
    "day_rules":         "낮 시간은 밤 시간 동안 어떤 행동들이 있었는지 추론하며 늑대인간을 찾아내는 시간입니다. 투표를 통해 처단할 플레이어를 결정합니다. 플레이어 중 늑대인간이 아무도 없다면 아무도 처단해서는 안 됩니다. 단, 늑대인간이 없어도 하수인이 있다면 하수인을 처단해야 마을주민팀이 승리합니다. 늑대인간과 하수인이 모두 있다면 하수인이 아닌 늑대인간을 처단해야 마을주민팀이 승리합니다. 이때 하수인은 늑대인간 대신 본인이 처단당하도록 유도하여 늑대인간팀이 승리하도록 돕습니다. 그리고 늑대인간의 존재 여부와 상관 없이 무두장이가 처단된다면 무두장이 혼자 승리합니다.",
}

# ── 요트다이스 ────────────────────────────────────────────────────────────────
# FSM은 이 line_id와 파라미터만 내보낸다(state.narration). 문장 조립은 여기서 한다.
# 화면 상태줄(last_message)도 같은 문장을 렌더해 쓰므로 화면과 음성이 어긋나지 않는다.
_YACHT: dict[str, str] = {
    "turn_start":       "{player}님, 주사위를 굴려주세요.",
    "reroll_prompt":    "{player}님, 다시 굴려주세요.",
    "roll_final":       "주사위 결과는 {values}입니다. 점수 칸을 선택해주세요.",
    "roll_partial":     "기회 {remaining} 남았습니다. 다시 굴리거나 점수 칸을 선택해주세요.",
    "dice_escaped":     "주사위가 트레이 밖으로 나갔습니다. 다시 굴려주세요.",
    "wrong_turn":       "지금은 {player}님 차례입니다.",
    "dice_unreadable":  "읽히지 않은 주사위 값이 있습니다. 화면에서 값을 입력해주세요.",
    "undo_roll":        "{player}님의 주사위 굴림을 되돌렸습니다.",
    # 이름 슬롯과 족보 이름 사이에 쉼표를 둔다. TTS가 공백을 끊어 읽을 자리로
    # 보는데, 쉼표가 없으면 "성민님풀 / 하우스 / 25점입니다"처럼 엉뚱한 데서
    # 끊긴다. 쉼표 하나가 그 자리를 잡아준다.
    "score_recorded":   "{scorer}님, {label} {score}점입니다. {next}님 차례입니다.",
    "game_finish":      "{scorer}님, {label} {score}점입니다. 게임이 종료되었습니다.",
    # 튜토리얼: 매 턴 반복되므로 짧게. 굴리는 법은 화면 인트로가 한 번만 설명한다.
    "tutorial_turn_start": "{player}님 차례입니다. 주사위를 굴려주세요.",
    "tutorial_complete":   "튜토리얼이 끝났습니다. 게임 선택 화면으로 돌아가거나 정식 게임을 시작해보세요.",
    # 개발 모드 전용. 페르소나 변환 대상이 아니다.
    "dev_late_game":    "[개발] 후반 상황을 만들었습니다. {player}님이 크게 넣으면 역전 연출이 뜹니다.",
    # 튜토리얼 인트로 4장. 화면에는 더 자세한 설명(body)이 따로 있고 이건 음성용
    # 요약이다 — 읽어주는 말과 읽는 글은 밀도가 달라야 해서 일부러 나뉘어 있다.
    "intro_what":  "요트다이스는 주사위 다섯 개로 족보를 만드는 게임입니다. 점수판 열두 칸을 하나씩 채워가고, 총점이 가장 높은 사람이 이깁니다.",
    "intro_turn":  "한 턴에 주사위를 세 번까지 굴릴 수 있습니다. 마음에 드는 눈은 남기고 나머지만 다시 굴리면 됩니다.",
    "intro_table": "주사위는 직접 손으로 굴리고, 남길 주사위는 트레이 한쪽의 킵 존으로 옮겨주세요. 카메라가 알아서 읽습니다. 태블릿에서는 점수 칸만 고르면 됩니다.",
    "intro_score": "굴림이 끝나면 점수판에서 칸을 하나 골라주세요. 예상 점수가 미리 표시됩니다. 한 번 채운 칸은 다시 쓸 수 없으니 신중하게 고르세요.",
}

# ── 요트 튜토리얼 코치 (StrategyAgent) ────────────────────────────────────────
# 판단은 agents/tools/yacht_coach.py가, 문장은 여기가 소유한다.
# 조각으로 나뉘어 있는 것은 조건에 따라 뒷말이 붙었다 말았다 하기 때문이다.
# 칸 이름(4 of a Kind 등)은 화면 점수판 라벨 그대로다 — 한국어로 바꾸면 낭독은
# 자연스러워지지만 정작 어느 칸인지 못 찾는다.
_COACH: dict[str, str] = {
    "first_roll":      "주사위 5개를 트레이 안에 굴려주세요. 카메라가 눈을 읽습니다.",
    "reroll_mechanic": "남길 주사위는 트레이 한쪽의 킵 존으로 옮겨두고, 나머지만 다시 굴리면 됩니다.",
    # 조합이 완성됐을 때
    "hand_yacht":                  "요트입니다. 주사위 다섯 개가 모두 {face}입니다. 이 게임에서 가장 어려운 조합이니 더 굴리지 말고 Yacht 칸에 50점을 넣으세요.",
    "hand_large_straight":         "{run} 다섯 개가 이어졌습니다. 라지 스트레이트 30점이에요. 더 굴리면 깨지니 지금 L. Straight 칸에 넣으세요.",
    "hand_four_of_a_kind":         "{face} 네 개 모였습니다. 4 of a Kind 칸에 {score}점을 넣을 수 있어요.",
    "hand_four_of_a_kind_chase":   "아니면 남은 한 개만 다시 굴려서 {face} 다섯 개, 요트를 노려볼 수도 있어요.",
    "hand_full_house":             "{triple} 세 개, {pair} 두 개라서 풀 하우스입니다. Full House 칸에 {score}점을 넣을 수 있어요.",
    "hand_small_straight":         "{run} 이어져서 스몰 스트레이트 15점을 확보했습니다.",
    "hand_small_straight_chase":   "남은 한 개를 다시 굴려서 다섯 개를 잇는 라지 스트레이트 30점을 노려볼 수도 있어요.",
    # 세 번을 다 굴렸을 때
    "last_call":      "세 번을 다 굴렸으니 이제 칸을 골라야 합니다. 지금 눈으로는 {label} 칸이 {score}점으로 가장 큽니다.",
    "last_call_zero": "세 번을 다 굴렸는데 점수가 되는 칸이 없네요. 이럴 때는 나중에 채우기 어려운 칸 하나를 0점으로 비워두는 편이 손해가 적습니다.",
    # 아직 굴릴 기회가 남았을 때
    "keep_triple":       "{face} 세 개 있습니다. 이 셋을 남기고 나머지 두 개만 다시 굴리면 4 of a Kind나 요트까지 노려볼 수 있어요.",
    "keep_triple_bonus": "그대로 {label} 칸에 넣어 상단 보너스를 쌓아도 좋고요.",
    "keep_run":          "{run} 이어져 있습니다. 이 셋을 남기고 나머지를 다시 굴리면 스트레이트를 노려볼 수 있어요.",
    "keep_pair":         "{face} 두 개 있습니다. 이 둘을 남기고 다시 굴려 개수를 늘려볼 수 있어요.",
    "keep_none":         "아직 뚜렷한 조합이 없습니다. 큰 눈 한두 개만 남기고 나머지를 다시 굴려보세요.",
    "fallback_best":     "지금 멈춘다면 {label} 칸이 {score}점으로 가장 큽니다.",
    "fallback_none":     "지금은 점수가 되는 칸이 없으니 한 번 더 굴려보는 게 좋겠어요.",
}


# ── 전략 조언 (StrategyAgent) ─────────────────────────────────────────────────
# 튜토리얼 코치(coach.*)와 다르다. 코치는 처음 하는 사람에게 조작과 선택지를
# 설명하고, 이쪽은 이미 아는 사람에게 한 줄로 훈수를 둔다.
# 판단은 tools/yacht_coach.py와 tools/werewolf_coach.py가 한다.
_STRATEGY: dict[str, str] = {
    # 요트: 지금 눈으로 가장 높은 칸
    "yacht_best": "현재 주사위 조합에서는 {label}에 기록하면 {score}점을 얻을 수 있습니다.",
    "yacht_none": "현재 주사위로 점수가 나오는 카테고리가 없습니다. 낮은 값을 가진 카테고리에 0을 기록하는 것을 추천합니다.",
    # 늑대인간: 역할별 야간 행동 요령. 시스템은 누가 어떤 역할인지 모르므로
    # 특정인을 지목하지 않고 그 역할의 일반적인 움직임만 말한다.
    "ww_doppelganger": "도플갱어는 다른 플레이어의 카드를 몰래 확인해 그 역할을 복사합니다. 강력한 역할(예언자, 도둑)을 노리세요.",
    "ww_seer": "예언자는 다른 플레이어 카드 한 장 또는 센터 카드 두 장을 볼 수 있습니다. 의심스러운 플레이어의 카드를 확인하는 것이 효과적입니다.",
    "ww_robber": "도둑은 다른 플레이어와 카드를 교환할 수 있습니다. 강력한 역할을 가진 플레이어의 카드를 노리세요.",
    "ww_troublemaker": "말썽꾼은 두 플레이어의 카드를 교환합니다. 늑대인간으로 의심되는 플레이어와 다른 플레이어의 카드를 바꿔 혼란을 주세요.",
    "ww_drunk": "주정뱅이는 센터 카드 중 하나와 자신의 카드를 교환합니다. 자신의 새 역할을 알 수 없으니 낮 토론에서 신중하게 행동하세요.",
    "ww_insomniac": "불면증 환자는 밤이 끝난 후 자신의 최종 카드를 확인합니다. 카드가 바뀌었다면 누군가 손을 댔다는 단서가 됩니다.",
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


_WEREWOLF_PRACTICE: dict[str, str] = {**_WEREWOLF, **_WEREWOLF_PRACTICE_OVERRIDES}

LINES: dict[str, str] = {
    **{f"werewolf.{k}": v for k, v in _WEREWOLF.items()},
    **{f"werewolf_practice.{k}": v for k, v in _WEREWOLF_PRACTICE.items()},
    **{f"yacht.{k}": v for k, v in _YACHT.items()},
    **{f"coach.{k}": v for k, v in _COACH.items()},
    **{f"strategy.{k}": v for k, v in _STRATEGY.items()},
    **{f"rules.{k}": v for k, v in _RULES.items()},
    **{f"tempo.{k}": v for k, v in _TEMPO.items()},
}


# ── 페르소나 말투 ──────────────────────────────────────────────────────────────
# LINES는 중립 원문이다. 페르소나를 고르면 같은 line_id를 그 말투로 바꾼 문장이
# 덮어쓴다. 변환은 런타임이 아니라 미리 해두고 JSON으로 갖고 있는다 —
# 발화할 때마다 LLM을 부르면 매 페이즈에 생성+합성 지연이 겹쳐 진행이 끊긴다.
#
# 덮어쓰지 못한 line_id는 원문 그대로 나간다. 말투가 안 바뀐 문장 하나가
# 게임이 멈추는 것보다 낫다.
PERSONA_LINES_DIR = Path(__file__).resolve().parent / "persona_lines"

_persona_id: str | None = None
_persona_lines: dict[str, str] = {}


def active_persona_id() -> str | None:
    return _persona_id


def set_persona_lines(persona_id: str | None, overrides: dict[str, str]) -> None:
    """변환된 문장을 적용한다. 검사를 통과한 것만 넘길 것."""
    global _persona_id, _persona_lines
    _persona_id = persona_id
    _persona_lines = dict(overrides)


def load_persona_lines(persona_id: str) -> tuple[dict[str, str], dict[str, list[str]]]:
    """<persona_id>.json을 읽어 검사한다. (통과분, 문제) 반환.

    파일이 없으면 빈 결과 — 아직 변환하지 않은 페르소나는 원문으로 진행한다.
    손으로 쓴 파일도 여기서 검사되므로, 슬롯을 빠뜨리면 로드 시점에 걸린다.
    """
    path = PERSONA_LINES_DIR / f"{persona_id}.json"
    if not path.exists():
        return {}, {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {}, {"__file__": [f"읽을 수 없음: {exc}"]}
    if not isinstance(raw, dict):
        return {}, {"__file__": ["최상위가 객체가 아님"]}
    return validate_all(LINES, {str(k): str(v) for k, v in raw.items()})


def use_persona(persona_id: str | None) -> tuple[int, dict[str, list[str]]]:
    """페르소나 말투를 적용한다. (적용된 줄 수, 검사에 걸린 항목) 반환.

    None이면 중립 원문으로 되돌린다.
    """
    if persona_id is None:
        set_persona_lines(None, {})
        return 0, {}
    accepted, rejected = load_persona_lines(persona_id)
    set_persona_lines(persona_id, accepted)
    return len(accepted), rejected


def catalog() -> dict[str, str]:
    """프론트에 내려보낼 전체 멘트 목록.

    프론트도 화면에 같은 문장을 그려야 해서(타이핑 애니메이션 등) 문장이 필요하다.
    발화할 때마다 왕복하면 애니메이션 타이밍이 흔들리므로 접속 시 통째로 준다.
    페르소나가 바뀌면 이 결과가 통째로 달라지고, 화면과 음성이 함께 바뀐다.
    """
    return {**LINES, **_persona_lines}


def get(line_id: str) -> str | None:
    """line_id의 템플릿. 페르소나 말투가 있으면 그것, 없으면 중립 원문."""
    return _persona_lines.get(line_id) or LINES.get(line_id)


def original(line_id: str) -> str | None:
    """페르소나와 무관한 중립 원문. 변환 대상 목록을 만들 때 쓴다."""
    return LINES.get(line_id)


def render(line_id: str, **params: object) -> str | None:
    """line_id를 params로 채워 실제 발화 문장으로. 없는 line_id면 None.

    str.format을 쓰지 않는다 — 멘트에 중괄호가 섞여 있거나 params가 비면
    KeyError로 발화 자체가 죽는다. 채울 수 있는 슬롯만 채우고 나머지는 둔다.
    """
    template = get(line_id)
    if template is None:
        return None
    return fill(template, **params)


def fill(template: str, **params: object) -> str:
    """템플릿의 {key} 슬롯을 params로 치환. 값이 없는 슬롯은 빈 문자열로."""
    def _sub(match: re.Match[str]) -> str:
        value = params.get(match.group(1))
        return "" if value is None else str(value)

    return re.sub(r"\{(\w+)\}", _sub, template)
