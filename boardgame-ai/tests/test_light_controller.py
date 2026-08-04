"""LightController 동작 검증. 하드웨어 없이 MockDriver로 전부 확인한다."""

from __future__ import annotations

import asyncio

import pytest

from bulb.config import LightConfig
from bulb.controller import LightController
from bulb.driver.mock import MockDriver
from bulb.scenes import BLACKOUT_SCENE, NEUTRAL_SCENE, Cue, Scene
from core.constants import MsgType
from core.envelope import WSMessage

RED = (255, 0, 0)
GOLD = (255, 200, 60)

_SCENES = {
    "werewolf": {
        "night_start": BLACKOUT_SCENE,
        "night_werewolf": Scene("ww_night", RED, brightness=15, transition_ms=1200),
        "day_discussion": Scene("ww_day", (255, 230, 200), brightness=100, transition_ms=2500),
    },
    "yacht": {
        "awaiting_roll": NEUTRAL_SCENE,
        "awaiting_score": NEUTRAL_SCENE,
    },
}

_CUES = {
    "yacht_turn_transition": Cue(
        "turn_sweep", GOLD, brightness=100, rise_ms=200, hold_ms=400, fall_ms=200
    ),
}


def _config(**overrides) -> LightConfig:
    base = {"command_timeout_s": 0.5}
    base.update(overrides)
    return LightConfig(**base)


def _controller(driver: MockDriver, **cfg) -> LightController:
    return LightController(driver, _config(**cfg), scene_map=_SCENES, cue_map=_CUES)


def _state(phase: str) -> WSMessage:
    return WSMessage(msg_type=MsgType.STATE_UPDATE.value, payload={"phase": phase})


def _cue(name: str, duration_ms: int = 2200) -> WSMessage:
    return WSMessage.make_cue(name, {"duration_ms": duration_ms})


async def _settle() -> None:
    """백그라운드 태스크가 끝날 때까지 양보."""
    for _ in range(10):
        await asyncio.sleep(0)


# ── Scene ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_phase_change_applies_mapped_scene():
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("day_discussion"), game="werewolf")
    await _settle()

    color, brightness, duration = driver.last
    assert color == (255, 230, 200)
    assert brightness == 100
    assert duration == 2500


@pytest.mark.asyncio
async def test_unmapped_phase_falls_back_to_neutral():
    """늑대인간 담당자가 페이즈를 추가해도 조명이 깨지지 않아야 한다.

    role_registration·card_setup 처럼 동결된 15개 목록에 없는 화면도 여기로
    떨어진다. 좌석 등록이 비전으로 돌아가는 구간이라 밝아야 맞다.
    """
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("role_registration"), game="werewolf")
    await _settle()

    color, brightness, _ = driver.last
    assert color == NEUTRAL_SCENE.color
    assert brightness == NEUTRAL_SCENE.brightness


@pytest.mark.asyncio
async def test_same_phase_repeated_sends_nothing_new():
    """state_update는 페이즈와 무관하게도 자주 온다. Yeelight 명령 수 제한 회피."""
    driver = MockDriver()
    controller = _controller(driver)

    for _ in range(5):
        controller.on_message(_state("day_discussion"), game="werewolf")
        await _settle()

    assert len(driver.applied) == 1


# ── 밝기 하한 ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_werewolf_night_can_go_fully_dark():
    """늑대인간 밤은 완전 소등에서 시작한다. 밤에는 비전이 할 일이 없다."""
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("night_start"), game="werewolf")
    await _settle()

    assert driver.last[1] == 0


@pytest.mark.asyncio
async def test_yacht_brightness_never_drops_below_floor():
    """요트에서 이 전구는 곧 주사위 인식 조명이다. 어두워지면 못 읽는다.

    매핑이 실수로 어두운 값을 넣어도 컨트롤러가 걷어올린다.
    """
    driver = MockDriver()
    controller = LightController(
        driver,
        _config(),
        scene_map={"yacht": {"awaiting_roll": Scene("oops", RED, brightness=5)}},
        cue_map=_CUES,
    )

    controller.on_message(_state("awaiting_roll"), game="yacht")
    await _settle()

    assert driver.last[1] == _config().floor_for("yacht")


@pytest.mark.asyncio
async def test_blackout_in_yacht_is_clamped_away():
    driver = MockDriver()
    controller = LightController(
        driver,
        _config(),
        scene_map={"yacht": {"awaiting_roll": BLACKOUT_SCENE}},
    )

    controller.on_message(_state("awaiting_roll"), game="yacht")
    await _settle()

    assert driver.last[1] >= _config().floor_for("yacht")


# ── Cue 복귀 보장 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cue_returns_to_scene():
    """Cue의 계약: 반드시 Scene으로 복귀하며 끝난다.

    복귀 실패는 요트에서 곧바로 인식 실패다.
    """
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("awaiting_roll"), game="yacht")
    await _settle()
    scene_state = driver.last

    controller.on_message(_cue("yacht_turn_transition"), game="yacht")
    await asyncio.sleep(0.9)

    assert driver.last[:2] == scene_state[:2]
    # 중간에 실제로 큐 색이 나갔는지 — 복귀만 하고 아무 일도 없으면 안 된다.
    assert any(applied[0] == GOLD for applied in driver.applied)


@pytest.mark.asyncio
async def test_unknown_cue_is_ignored():
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("awaiting_roll"), game="yacht")
    await _settle()
    before = len(driver.applied)

    controller.on_message(_cue("nonexistent_cue"), game="yacht")
    await _settle()

    assert len(driver.applied) == before


@pytest.mark.asyncio
async def test_cue_longer_than_modal_duration_warns(caplog):
    """설계문서 §2.4 불변식: 모달 duration >= Cue 전체 길이(복귀 페이드 포함)."""
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_cue("yacht_turn_transition", duration_ms=100), game="yacht")
    await _settle()

    assert any("인식이 깨질 수 있다" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_scene_change_during_cue_wins():
    """Cue 재생 중 페이즈가 바뀌면 새 Scene이 이긴다. 조명이 멈춰 있으면 안 된다."""
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("awaiting_roll"), game="yacht")
    await _settle()
    controller.on_message(_cue("yacht_turn_transition"), game="yacht")
    await asyncio.sleep(0.05)

    controller.on_message(_state("day_discussion"), game="werewolf")
    await asyncio.sleep(0.6)

    assert driver.last[0] == (255, 230, 200)


# ── 장애 격리 ────────────────────────────────────────────────────────────────


class _BrokenDriver(MockDriver):
    async def apply(self, color, brightness, duration_ms):
        raise RuntimeError("전구 연결 끊김")


class _HangingDriver(MockDriver):
    async def apply(self, color, brightness, duration_ms):
        await asyncio.sleep(10)


@pytest.mark.asyncio
async def test_driver_failure_never_reaches_caller():
    """조명 코드가 게임을 깨뜨릴 권한은 없다."""
    controller = _controller(_BrokenDriver())

    controller.on_message(_state("day_discussion"), game="werewolf")
    await _settle()  # 예외가 새면 여기서 터진다


@pytest.mark.asyncio
async def test_hanging_driver_does_not_block_caller():
    """소켓 지연이 게임 진행을 멈추면 안 된다."""
    controller = _controller(_HangingDriver(), command_timeout_s=0.1)

    loop = asyncio.get_running_loop()
    before = loop.time()
    controller.on_message(_state("day_discussion"), game="werewolf")
    elapsed = loop.time() - before

    assert elapsed < 0.05


@pytest.mark.asyncio
async def test_failed_command_is_not_deduped_away():
    """실패한 명령을 "보냈다"고 캐시하면 다음 복귀 명령이 삼켜진다.

    삼켜지는 게 중립 복귀라면 요트 인식이 그대로 깨진다.
    """
    driver = _BrokenDriver()
    controller = _controller(driver)

    controller.on_message(_state("day_discussion"), game="werewolf")
    await _settle()
    controller._game = None  # 페이즈 dedup을 우회해 같은 Scene을 다시 요청
    controller.on_message(_state("day_discussion"), game="werewolf")
    await _settle()

    assert controller._last_applied is None


@pytest.mark.asyncio
async def test_disabled_controller_does_nothing():
    driver = MockDriver()
    controller = LightController(driver, _config(enabled=False), scene_map=_SCENES)

    controller.on_message(_state("day_discussion"), game="werewolf")
    await _settle()

    assert driver.applied == []


# ── 생명주기 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_start_lights_the_room_before_any_game():
    """부팅 직후 전구를 중립으로 올린다.

    로비는 세션을 거치지 않고 브로드캐스트해서 조명 스트림에 잡히지 않는다.
    좌석 등록이 비전으로 돌아가는 구간의 밝기는 이 기본값이 유일한 보장이다.
    """
    driver = MockDriver()
    controller = _controller(driver)
    assert driver.applied == []

    await controller.start()

    assert driver.last[0] == NEUTRAL_SCENE.color
    assert driver.last[1] == NEUTRAL_SCENE.brightness


@pytest.mark.asyncio
async def test_reset_returns_to_neutral():
    """다음 세션이 이전 세션의 색을 물려받지 않게 한다."""
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("night_start"), game="werewolf")
    await _settle()
    await controller.reset()

    assert driver.last[0] == NEUTRAL_SCENE.color
    assert driver.last[1] == NEUTRAL_SCENE.brightness


@pytest.mark.asyncio
async def test_aclose_restores_neutral_and_closes_driver():
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("night_start"), game="werewolf")
    await _settle()
    await controller.aclose()

    assert driver.last[1] == NEUTRAL_SCENE.brightness
    assert driver.closed


class _SlowDriver(MockDriver):
    """전구가 응답하는 데 시간이 걸리는 상황. 실제 소켓이 그렇다."""

    async def apply(self, color, brightness, duration_ms):
        await asyncio.sleep(0.12)
        await super().apply(color, brightness, duration_ms)


@pytest.mark.asyncio
async def test_reset_wins_over_a_scene_that_is_still_in_flight():
    """정리했다고 믿는 순간이 가장 위험하다.

    Scene 적용도 백그라운드 태스크라, 취소하지 않으면 중립을 세운 직후에 뒤늦게
    완료되면서 다른 색으로 덮어쓴다.
    """
    driver = _SlowDriver()
    controller = _controller(driver, command_timeout_s=5.0)

    controller.on_message(_state("night_start"), game="werewolf")
    await asyncio.sleep(0.02)  # 암전 적용이 아직 날아가는 중

    await controller.reset()
    await asyncio.sleep(0.3)  # 취소된 명령이 뒤늦게 끝날 여유

    assert driver.last is not None
    assert driver.last[0] == NEUTRAL_SCENE.color
    assert driver.last[1] == NEUTRAL_SCENE.brightness
    assert 0 not in [applied[1] for applied in driver.applied], "취소된 암전이 뒤늦게 적용됐다"


@pytest.mark.asyncio
async def test_cancelled_command_does_not_block_the_next_one():
    """취소된 명령이 전구까지 갔는지 알 수 없다.

    "보냈다"고 캐시해두면 뒤이은 중립 복귀가 중복 제거로 삼켜져 조명이 색을 문
    채 멈춘다. 요트에서는 그대로 인식 실패다.
    """
    driver = _HangingDriver()
    controller = _controller(driver, command_timeout_s=5.0)

    task = controller._spawn(
        controller._drive(NEUTRAL_SCENE.color, NEUTRAL_SCENE.brightness, 0, "yacht")
    )
    await asyncio.sleep(0.02)
    task.cancel()
    await asyncio.sleep(0.02)

    assert controller._last_applied is None, "취소된 명령이 캐시에 남았다"


@pytest.mark.asyncio
async def test_reset_recovers_light_stuck_mid_cue():
    """Cue 도중 세션이 끊겨도 조명이 색을 문 채 멈추지 않는다."""
    driver = MockDriver()
    controller = _controller(driver)

    controller.on_message(_state("awaiting_roll"), game="yacht")
    await _settle()
    controller.on_message(_cue("yacht_turn_transition"), game="yacht")
    await asyncio.sleep(0.05)
    assert driver.last[0] == GOLD

    await controller.reset()

    assert driver.last[0] == NEUTRAL_SCENE.color
