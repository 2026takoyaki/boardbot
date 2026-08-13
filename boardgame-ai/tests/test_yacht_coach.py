"""요트 튜토리얼 코치 — 프론트(yachtCoach.js)에서 넘어온 판단 로직.

코치는 처음 하는 사람이 유일하게 기대는 안내라, 틀린 조언을 하면 튜토리얼이
튜토리얼 구실을 못 한다. 조합별로 무엇을 권하는지와, 같은 말을 반복하지 않는지를
확인한다.
"""

from __future__ import annotations

import pytest

from agents.context import AgentContext
from agents.strategy_agent import StrategyAgent
from agents.tools import lines, yacht_coach

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


def _ids(dice: list[int], available: list[str] | None = None, roll_count: int = 1) -> list[str]:
    advice = yacht_coach.advise(dice, available if available is not None else ALL_OPEN, roll_count)
    assert advice is not None
    return [line_id for line_id, _ in advice.fragments]


def _text(dice: list[int], available: list[str] | None = None, roll_count: int = 1) -> str:
    advice = yacht_coach.advise(dice, available if available is not None else ALL_OPEN, roll_count)
    assert advice is not None
    return " ".join(lines.render(i, **p) or "" for i, p in advice.fragments)


# ── 조합이 완성된 경우 ─────────────────────────────────────────────────────────


def test_요트는_더_굴리지_말라고_한다() -> None:
    assert _ids([4, 4, 4, 4, 4]) == ["coach.hand_yacht"]
    assert "50점" in _text([4, 4, 4, 4, 4])


def test_라지스트레이트는_깨지니_넣으라고_한다() -> None:
    assert _ids([2, 3, 4, 5, 6]) == ["coach.hand_large_straight"]


def test_포카드는_기회가_남으면_요트를_권한다() -> None:
    assert _ids([5, 5, 5, 5, 2], roll_count=1) == [
        "coach.hand_four_of_a_kind",
        "coach.hand_four_of_a_kind_chase",
    ]


def test_포카드도_마지막_굴림이면_요트를_권하지_않는다() -> None:
    """굴릴 기회가 없는데 노려보라고 하면 지킬 수 없는 조언이다."""
    assert _ids([5, 5, 5, 5, 2], roll_count=3) == ["coach.hand_four_of_a_kind"]


def test_요트칸이_찼으면_요트를_권하지_않는다() -> None:
    available = [c for c in ALL_OPEN if c != "yacht"]
    assert _ids([5, 5, 5, 5, 2], available, roll_count=1) == ["coach.hand_four_of_a_kind"]


def test_풀하우스는_세개와_두개를_짚어준다() -> None:
    assert _ids([3, 3, 3, 6, 6]) == ["coach.hand_full_house"]
    text = _text([3, 3, 3, 6, 6])
    assert "3이 세 개" in text
    assert "6이 두 개" in text


def test_스몰스트레이트는_라지를_노려보라고_한다() -> None:
    assert _ids([2, 3, 4, 5, 5]) == [
        "coach.hand_small_straight",
        "coach.hand_small_straight_chase",
    ]


# ── 아직 굴릴 기회가 남은 경우 ─────────────────────────────────────────────────


def test_같은_눈_셋이면_남기라고_한다() -> None:
    ids = _ids([2, 2, 2, 3, 5])
    assert ids[0] == "coach.keep_triple"
    assert "coach.keep_triple_bonus" in ids  # twos 칸이 비어 있다


def test_상단칸이_찼으면_보너스_이야기를_하지_않는다() -> None:
    available = [c for c in ALL_OPEN if c != "twos"]
    assert _ids([2, 2, 2, 3, 5], available) == ["coach.keep_triple"]


def test_세개_이어지면_스트레이트를_권한다() -> None:
    assert _ids([3, 4, 5, 1, 1])[0] == "coach.keep_run"


def test_뚜렷한_조합이_없으면_큰_눈을_남기라고_한다() -> None:
    """다섯 눈이 모두 다르면 반드시 셋 이상 이어지므로(1~6 중 다섯 개를 고르면
    빠진 값이 하나뿐이다) 스트레이트 칸이 남아 있는 한 여기까지 오지 않는다.
    스트레이트를 이미 채운 뒤에야 "뚜렷한 조합이 없다"가 성립한다."""
    available = [c for c in ALL_OPEN if c not in ("small_straight", "large_straight")]
    assert _ids([1, 2, 3, 4, 6], available)[0] == "coach.keep_none"


def test_마지막_굴림이면_칸을_고르라고_한다() -> None:
    assert _ids([1, 3, 5, 2, 6], roll_count=3) == ["coach.last_call"]


# ── 조사 ───────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1", "1이"),
        ("2", "2가"),
        ("3", "3이"),
        ("4", "4가"),
        ("5", "5가"),
        ("6", "6이"),
        ("3-4-5", "3-4-5가"),
        ("1-2-3", "1-2-3이"),
    ],
)
def test_받침에_맞는_조사를_붙인다(value: str, expected: str) -> None:
    """'5이 세 개'는 눈에 거슬리고, TTS로 읽히면 더 티가 난다.
    이어진 눈("3-4-5")은 마지막 숫자를 기준으로 판단한다."""
    assert yacht_coach._with_josa(value, "이", "가") == expected


def test_조사가_실제_조언에도_반영된다() -> None:
    assert "5가 세 개" in _text([5, 5, 5, 1, 2])
    assert "3이 세 개" in _text([3, 3, 3, 1, 5])


# ── 눈이 온전하지 않은 경우 ────────────────────────────────────────────────────


def test_읽히지_않은_눈이_있으면_조언하지_않는다() -> None:
    """틀린 눈으로 조언하느니 아무 말도 안 하는 편이 낫다."""
    assert yacht_coach.advise([1, 2, None, 4, 5], ALL_OPEN, 1) is None  # type: ignore[list-item]
    assert yacht_coach.advise([1, 2, 3], ALL_OPEN, 1) is None


def test_모든_칸이_찼으면_조언하지_않는다() -> None:
    assert yacht_coach.advise([1, 2, 3, 4, 5], [], 1) is None


# ── StrategyAgent 연동 ────────────────────────────────────────────────────────


def _ctx(fsm_state: str, dice: list[int], roll_count: int, tutorial: bool = True) -> AgentContext:
    return AgentContext(
        game_type="yacht",
        fsm_state=fsm_state,
        active_player="p1",
        players=[{"player_id": "p1", "playername": "성민"}],
        game_specific={
            "dice_values": dice,
            "available_categories": ALL_OPEN,
            "roll_count": roll_count,
            "tutorial_mode": tutorial,
        },
    )


@pytest.mark.anyio
async def test_튜토리얼이_아니면_코치가_말하지_않는다() -> None:
    agent = StrategyAgent()
    result = await agent.on_state_change_async(_ctx("AWAITING_KEEP", [3, 3, 3, 1, 2], 1, False))
    assert result is None


@pytest.mark.anyio
async def test_튜토리얼이면_토글_없이도_코치가_말한다() -> None:
    """처음 하는 사람에게 '조언 켜기'를 먼저 찾게 하는 것은 순서가 뒤집혔다."""
    agent = StrategyAgent()
    assert agent.enabled is False
    result = await agent.on_state_change_async(_ctx("AWAITING_KEEP", [3, 3, 3, 1, 2], 1))
    assert result is not None
    assert result.display is True
    assert result.tts_text and "3이 세 개" in result.tts_text


@pytest.mark.anyio
async def test_같은_눈을_다시_보면_말하지_않는다() -> None:
    agent = StrategyAgent()
    ctx = _ctx("AWAITING_KEEP", [3, 3, 3, 1, 2], 1)
    assert await agent.on_state_change_async(ctx) is not None
    assert await agent.on_state_change_async(ctx) is None


@pytest.mark.anyio
async def test_조작법은_한_번만_붙는다() -> None:
    """조언 자체는 매번 다르지만 조작법은 한 번이면 족하다."""
    agent = StrategyAgent()
    first = await agent.on_state_change_async(_ctx("AWAITING_KEEP", [3, 3, 3, 1, 2], 1))
    second = await agent.on_state_change_async(_ctx("AWAITING_KEEP", [4, 4, 4, 1, 2], 1))
    assert first is not None and second is not None
    mechanic = lines.get("coach.reroll_mechanic")
    assert mechanic and first.tts_text and second.tts_text
    assert mechanic in first.tts_text
    assert mechanic not in second.tts_text


@pytest.mark.anyio
async def test_굴리기_전_안내는_첫_사람에게만() -> None:
    agent = StrategyAgent()
    first = await agent.on_state_change_async(_ctx("AWAITING_ROLL", [], 0))
    assert first is not None and first.tts_text == lines.get("coach.first_roll")
    assert first.transient is True

    # 다음 사람 차례. 같은 안내를 또 읽으면 세 명이면 세 번 듣는다.
    await agent.on_state_change_async(_ctx("AWAITING_KEEP", [3, 3, 3, 1, 2], 1))
    again = await agent.on_state_change_async(_ctx("AWAITING_ROLL", [], 0))
    assert again is not None
    assert again.tts_text is None  # 화면만 비우고 발화는 하지 않는다
    assert again.display is True


@pytest.mark.anyio
async def test_새_판에서는_조작법을_다시_설명한다() -> None:
    agent = StrategyAgent()
    await agent.on_state_change_async(_ctx("AWAITING_ROLL", [], 0))
    agent.reset_coach()
    again = await agent.on_state_change_async(_ctx("AWAITING_ROLL", [], 0))
    assert again is not None and again.tts_text == lines.get("coach.first_roll")


# ── 흥분 톤 ────────────────────────────────────────────────────────────────────
# 모든 족보에 흥분하면 아무것도 특별하지 않다. 요트가 터졌을 때 올릴 톤이
# 남아 있어야 한다.


@pytest.mark.parametrize(
    ("dice", "expected"),
    [
        ([5, 5, 5, 5, 5], True),  # 요트
        ([2, 3, 4, 5, 6], True),  # 라지스트레이트
        ([3, 3, 3, 3, 1], False),  # 포카드
        ([2, 2, 2, 5, 5], False),  # 풀하우스
        ([1, 2, 3, 4, 6], False),  # 스몰스트레이트
    ],
)
def test_희귀한_족보에만_흥분한다(dice: list[int], expected: bool) -> None:
    advice = yacht_coach.advise(dice, ALL_OPEN, 1)
    assert advice is not None
    assert advice.excited is expected


def test_굴리는_중_조언은_흥분하지_않는다() -> None:
    """아직 아무것도 안 터졌는데 소리를 지르면 김이 샌다."""
    advice = yacht_coach.advise([2, 2, 3, 5, 6], ALL_OPEN, 1)
    assert advice is not None and advice.excited is False


@pytest.mark.anyio
async def test_흥분한_조언은_다른_말투를_요청한다() -> None:
    """목소리는 그대로고 톤만 올라간다."""
    from core.persona import DELIVERY_EXCITED

    agent = StrategyAgent()
    ctx = _ctx("AWAITING_SCORE", [5, 5, 5, 5, 5], 1)
    result = await agent.on_state_change_async(ctx)

    assert result is not None
    assert result.delivery == DELIVERY_EXCITED


@pytest.mark.anyio
async def test_평범한_조언은_기본_말투다() -> None:
    agent = StrategyAgent()
    result = await agent.on_state_change_async(_ctx("AWAITING_KEEP", [3, 3, 3, 1, 2], 1))
    assert result is not None
    assert result.delivery is None
