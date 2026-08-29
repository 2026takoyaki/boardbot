"""전략 조언(훈수) — 튜토리얼 코치와 다른 경로.

코치는 처음 하는 사람에게 조작과 선택지를 설명하고, 훈수는 이미 아는 사람에게
한 줄로 알려준다. 둘 다 StrategyAgent가 맡지만 켜지는 조건이 다르다.

여기서 지키는 것: 문장이 에이전트에 박혀 있지 않다는 것. 박혀 있으면
페르소나가 닿지 않는다.
"""

from __future__ import annotations

import pytest

from agents.context import AgentContext
from agents.strategy_agent import StrategyAgent
from agents.tools import lines, werewolf_coach, yacht_coach

ALL_OPEN = [
    "ones",
    "twos",
    "threes",
    "fours",
    "fives",
    "sixes",
    "choice",
    "four_of_a_kind",
    "full_house",
    "small_straight",
    "large_straight",
    "yacht",
]


def _ctx(game_type: str, fsm_state: str, **game_specific: object) -> AgentContext:
    return AgentContext(
        game_type=game_type,
        fsm_state=fsm_state,
        active_player="p1",
        players=[{"player_id": "p1", "playername": "성민"}],
        game_specific=dict(game_specific),
    )


def _enabled() -> StrategyAgent:
    agent = StrategyAgent()
    agent.set_enabled(True)
    return agent


# ── 문장 소유권 ────────────────────────────────────────────────────────────────


def test_전략_문장이_lines에_있다() -> None:
    """에이전트 안에 박혀 있으면 페르소나가 못 바꾼다."""
    for line_id in werewolf_coach.PHASE_TIPS.values():
        assert lines.get(line_id), f"{line_id} 없음"
    assert lines.get("strategy.yacht_best")
    assert lines.get("strategy.yacht_none")


# 야간 조언 한 줄의 글자 수 상한.
#
# 야간 단계는 짧다. 안내가 5초, 마지막 "눈을 다시 감아주세요"에 4초를 쓰고 나면
# 조언에 남는 것은 5초 남짓이고, 한국어 TTS는 초당 5~6자를 읽는다. 이 상한을
# 넘으면 조언이 끝나기 전에 단계가 넘어가 마감 지시가 통째로 잘린다.
_NIGHT_TIP_MAX_CHARS = 25


def test_야간_훈수는_한_단계_안에_들어갈_길이다() -> None:
    """기본 문구와 출고된 페르소나 문구 전부를 검사한다.

    한쪽만 줄이면 그 페르소나에서만 다시 잘린다 — 실제로 기본 문구를 줄이기
    전에는 여섯 줄이 55~75자였고, 앞 절반은 진행 안내가 방금 한 말이었다.
    """
    import json
    from pathlib import Path

    too_long: list[str] = []

    for line_id in werewolf_coach.PHASE_TIPS.values():
        text = lines.get(line_id)
        if len(text) > _NIGHT_TIP_MAX_CHARS:
            too_long.append(f"기본/{line_id} {len(text)}자")

    tip_ids = set(werewolf_coach.PHASE_TIPS.values())
    persona_dir = Path(__file__).resolve().parent.parent / "agents" / "tools" / "persona_lines"
    for path in sorted(persona_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        catalog = data.get("lines", data)
        for line_id, text in catalog.items():
            if line_id in tip_ids and len(text) > _NIGHT_TIP_MAX_CHARS:
                too_long.append(f"{path.stem}/{line_id} {len(text)}자")

    assert not too_long, (
        f"야간 훈수가 {_NIGHT_TIP_MAX_CHARS}자를 넘는다 — "
        f"단계 안에 안 들어가 마감 지시가 잘린다: {too_long}"
    )


def test_늑대인간_훈수가_lines에서_나온다() -> None:
    agent = _enabled()
    result = agent.on_state_change(_ctx("werewolf", "night_seer"))
    assert result is not None
    assert result.tts_text == lines.get("strategy.ww_seer")


def test_페르소나_말투가_훈수에도_걸린다() -> None:
    agent = _enabled()
    lines.set_persona_lines("test", {"strategy.ww_seer": "야 예언자, 수상한 놈 카드 까봐."})
    try:
        result = agent.on_state_change(_ctx("werewolf", "night_seer"))
        assert result is not None
        assert result.tts_text == "야 예언자, 수상한 놈 카드 까봐."
    finally:
        lines.use_persona(None)


# ── 발동 조건 ──────────────────────────────────────────────────────────────────


def test_토글이_꺼져_있으면_말하지_않는다() -> None:
    agent = StrategyAgent()
    assert agent.on_state_change(_ctx("werewolf", "night_seer")) is None


def test_조언할_것이_없는_페이즈는_침묵() -> None:
    """늑대인간·프리메이슨은 서로 확인만 하면 끝이라 훈수할 게 없다."""
    agent = _enabled()
    assert agent.on_state_change(_ctx("werewolf", "night_werewolf")) is None
    assert agent.on_state_change(_ctx("werewolf", "day_discussion")) is None


def test_요트는_굴린_뒤에만_훈수한다() -> None:
    agent = _enabled()
    ctx = _ctx("yacht", "AWAITING_ROLL", dice_values=[], available_categories=ALL_OPEN)
    assert agent.on_state_change(ctx) is None


# ── 요트 훈수 내용 ────────────────────────────────────────────────────────────


def test_가장_높은_칸을_알려준다() -> None:
    agent = _enabled()
    ctx = _ctx(
        "yacht",
        "AWAITING_SCORE",
        dice_values=[5, 5, 5, 5, 5],
        available_categories=ALL_OPEN,
    )
    result = agent.on_state_change(ctx)
    assert result is not None
    assert "요트" in result.tts_text and "50" in result.tts_text


def test_점수가_없으면_버릴_칸을_고르라고_한다() -> None:
    """0점인데 '여기 넣으세요'라고 하면 조언이 아니다."""
    agent = _enabled()
    ctx = _ctx(
        "yacht",
        "AWAITING_SCORE",
        dice_values=[1, 2, 3, 4, 6],
        available_categories=["yacht", "four_of_a_kind"],
    )
    result = agent.on_state_change(ctx)
    assert result is not None
    assert result.tts_text == lines.get("strategy.yacht_none")


def test_읽히지_않은_눈이_있으면_침묵() -> None:
    agent = _enabled()
    ctx = _ctx(
        "yacht",
        "AWAITING_SCORE",
        dice_values=[1, 2, None, 4, 5],
        available_categories=ALL_OPEN,
    )
    assert agent.on_state_change(ctx) is None


# ── 훈수는 낭독용 한글 이름을 쓴다 ────────────────────────────────────────────


def test_훈수는_한글_칸_이름을_쓴다() -> None:
    """코치는 화면의 그 칸을 가리켜야 해서 영문 라벨을 쓰지만, 훈수는 귀로만
    듣는 말이라 '엘 스트레이트'로 읽히면 안 된다."""
    agent = _enabled()
    ctx = _ctx(
        "yacht",
        "AWAITING_SCORE",
        dice_values=[2, 3, 4, 5, 6],
        available_categories=["large_straight"],
    )
    result = agent.on_state_change(ctx)
    assert result is not None
    assert "라지스트레이트" in result.tts_text
    assert "L. Straight" not in result.tts_text


@pytest.mark.parametrize("category", sorted(yacht_coach.KOREAN_LABEL))
def test_모든_칸에_한글_이름이_있다(category: str) -> None:
    assert yacht_coach.KOREAN_LABEL[category]
