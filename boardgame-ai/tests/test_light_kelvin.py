"""색온도 전달 검증.

흰색에 가까운 색을 RGB로 내면 전구마다 색이 갈린다. 실측에서 같은
(255,225,190)을 받은 두 전구가 각각 분홍·연두로 보였다. 색온도 모드는 전용
백색 LED를 쓰므로 그 편차가 사라진다.

여기서 보는 것은 "어떤 색이 색온도로 나가고 어떤 색이 RGB로 나가는가"와,
그 값이 드라이버까지 온전히 도착하는가다.
"""

from __future__ import annotations

import asyncio

import pytest

from bulb.config import LightConfig
from bulb.controller import LightController
from bulb.driver.base import KELVIN_MAX, KELVIN_MIN
from bulb.driver.mock import MockDriver
from bulb.scenes import (
    NEUTRAL_SCENE,
    YACHT_CUES,
    build_cue_map,
    build_scene_map,
)
from core.constants import MsgType
from core.envelope import WSMessage

# 채도가 이 아래면 흰색에 가깝다고 본다. 그 위는 다이 하나가 지배해서 개체
# 편차가 잘 안 보이므로 RGB로 둔다.
_WHITEISH_SATURATION = 0.55


def _saturation(rgb: tuple[int, int, int]) -> float:
    hi, lo = max(rgb), min(rgb)
    return 0.0 if hi == 0 else (hi - lo) / hi


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


def _controller(driver: MockDriver) -> LightController:
    return LightController(
        driver,
        LightConfig(command_timeout_s=0.5),
        scene_map=build_scene_map(night_brightness=15),
        cue_map=build_cue_map(),
    )


# ── 팔레트 규칙 ───────────────────────────────────────────────────────────────


def test_흰색에_가까운_씬은_색온도를_가진다() -> None:
    scenes = build_scene_map(night_brightness=15)
    missing = [
        f"{game}/{phase} {scene.color}"
        for game, phases in scenes.items()
        for phase, scene in phases.items()
        # 소등은 색이 의미 없다.
        if not scene.is_blackout
        and _saturation(scene.color) < _WHITEISH_SATURATION
        and scene.kelvin is None
    ]
    assert not missing, f"흰색에 가까운데 RGB로 나가는 씬: {missing}"


def test_흰색에_가까운_큐는_색온도를_쓰되_중립에_막히면_예외다() -> None:
    """큐의 기준은 "흰색인가"가 아니라 "중립과 구분되는가"다.

    중립이 전구 상한(6500K)에 있으면 그보다 서늘한 색온도가 없다. 그 경우
    RGB로 내는 것이 유일한 방법이고, 모드가 다르므로 출력은 확실히 갈린다.
    """
    neutral = NEUTRAL_SCENE.kelvin
    assert neutral is not None
    bad = []
    for name, cue in YACHT_CUES.items():
        if _saturation(cue.color) >= _WHITEISH_SATURATION or cue.kelvin is not None:
            continue
        # 색온도를 안 쓰는 흰색 계열 큐는 상한에 막힌 경우만 허용한다.
        if neutral < KELVIN_MAX:
            bad.append(f"{name} {cue.color} — 중립이 {neutral}K라 색온도로 낼 여지가 있다")
    assert not bad, bad


def test_채도가_높은_색은_RGB로_둔다() -> None:
    """늑대인간 역할 색은 원색이다. 색온도로는 낼 수 없다."""
    scenes = build_scene_map(night_brightness=15)["werewolf"]
    vivid = [
        (phase, scene)
        for phase, scene in scenes.items()
        if _saturation(scene.color) >= _WHITEISH_SATURATION
    ]
    assert vivid, "채도 높은 늑대인간 씬이 하나도 없다 — 팔레트가 바뀌었는지 확인하라"
    for phase, scene in vivid:
        assert scene.kelvin is None, f"{phase}는 원색인데 색온도가 붙어 있다"


def test_색온도가_전구_지원_범위_안이다() -> None:
    scenes = build_scene_map(night_brightness=15)
    values = [s.kelvin for phases in scenes.values() for s in phases.values() if s.kelvin]
    values += [c.kelvin for c in YACHT_CUES.values() if c.kelvin]
    assert values
    for k in values:
        assert KELVIN_MIN <= k <= KELVIN_MAX, f"{k}K는 전구가 낼 수 없다"


def test_주사위_인식_조명은_색온도로_나간다() -> None:
    """요트 전 구간과 로비의 바탕. RGB 혼색 백색보다 밝고 색이 고르다."""
    assert NEUTRAL_SCENE.kelvin is not None


# 중립과 이만큼은 떨어져야 눈에 보인다. 색온도가 붙은 명령은 RGB를 무시하므로
# 이보다 가까우면 color를 아무리 다르게 적어도 전구 출력이 같아진다.
_MIN_KELVIN_GAP = 800


def test_큐가_중립과_구분된다() -> None:
    """중립에 붙은 큐는 전구에서 안 보인다.

    NEUTRAL_KELVIN을 인식률 때문에 백색 쪽으로 올리면 upset·deflate처럼 원래
    서늘했던 큐가 중립에 흡수된다. color 값이 달라 중복 제거는 통과하므로
    로그에는 정상으로 찍히고, 전구만 아무 일도 하지 않는다.
    """
    neutral = NEUTRAL_SCENE.kelvin
    assert neutral is not None
    too_close = [
        f"{name} {cue.kelvin}K (중립 {neutral}K와 {abs(cue.kelvin - neutral)}K 차이)"
        for name, cue in YACHT_CUES.items()
        if cue.kelvin is not None and abs(cue.kelvin - neutral) < _MIN_KELVIN_GAP
    ]
    assert not too_close, f"중립과 구분되지 않는 큐: {too_close}"


def test_큐끼리도_서로_구분된다() -> None:
    """연출의 종류가 다르면 전구에서도 달라야 한다."""
    items = [(n, c.kelvin) for n, c in YACHT_CUES.items() if c.kelvin is not None]
    collisions = [
        f"{a}({ka}K) ↔ {b}({kb}K)"
        for i, (a, ka) in enumerate(items)
        for b, kb in items[i + 1 :]
        if abs(ka - kb) < _MIN_KELVIN_GAP
    ]
    assert not collisions, f"서로 구분되지 않는 큐: {collisions}"


# ── 전달 경로 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_씬의_색온도가_드라이버까지_간다() -> None:
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(
        WSMessage(msg_type=MsgType.STATE_UPDATE.value, payload={"phase": "day_discussion"}),
        game="werewolf",
    )
    await _settle()

    assert driver.calls, "새벽 씬이 적용되지 않았다"
    *_, kelvin = driver.calls[-1]
    assert kelvin is not None, "새벽은 흰색에 가까워 색온도로 나가야 한다"


@pytest.mark.asyncio
async def test_큐가_끝나면_씬의_색온도로_돌아온다() -> None:
    """복귀가 RGB로 이뤄지면 요트 바탕이 색온도에서 벗어난 채 남는다."""
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(
        WSMessage(msg_type=MsgType.STATE_UPDATE.value, payload={"phase": "AWAITING_ROLL"}),
        game="yacht",
    )
    await _settle()

    controller.on_message(
        WSMessage.make_cue("yacht_turn_transition", {"duration_ms": 2200}), game="yacht"
    )
    await asyncio.sleep(1.1)  # rise + hold 이후

    color, _brightness, _duration, kelvin = driver.calls[-1]
    assert color == NEUTRAL_SCENE.color
    assert kelvin == NEUTRAL_SCENE.kelvin


@pytest.mark.asyncio
async def test_전달_방식만_달라도_다시_보낸다() -> None:
    """RGB만 보고 중복 제거하면 전달 방식이 바뀐 전환이 통째로 삼켜진다."""
    driver = MockDriver()
    controller = _controller(driver)
    rgb = NEUTRAL_SCENE.color

    await controller._drive(rgb, 100, 100, "yacht", None)
    await controller._drive(rgb, 100, 100, "yacht", 4000)

    assert len(driver.calls) == 2
    assert driver.calls[0][3] is None
    assert driver.calls[1][3] == 4000
