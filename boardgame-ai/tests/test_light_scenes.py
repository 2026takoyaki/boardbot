"""Scene/Cue 매핑 테이블 검증.

색이 예쁜지는 실물로만 알 수 있다. 여기서 지키는 것은 **깨지면 게임이 망가지는
성질들**이다 — 요트 Cue의 복귀 시한, 페이즈 이름 계약, 밤의 어둠.
"""

from __future__ import annotations

import asyncio

import pytest

from bulb import build_controller
from bulb.config import LightConfig
from bulb.driver.mock import MockDriver
from bulb.scenes import (
    IN_PLAY_YACHT_CUES,
    NEUTRAL_SCENE,
    YACHT_CUES,
    build_cue_map,
    build_scene_map,
)
from core.constants import MsgType
from core.envelope import WSMessage
from games.werewolf.ontology import WerewolfPhase
from games.yacht.fsm import _CUE_DURATION_MS, _GAME_FINISH_CUE_DURATION_MS
from games.yacht.state import YachtPhase

# FSM이 발행하는 큐 이름 → 그 큐가 싣고 오는 duration_ms.
# 이 대응이 어긋나면 조명이 모달보다 늦게 복귀한다.
_CUE_BUDGETS = {
    "yacht_turn_transition": _CUE_DURATION_MS["normal"],
    "yacht_turn_transition_highlight": _CUE_DURATION_MS["highlight"],
    "yacht_turn_transition_lead_change": _CUE_DURATION_MS["lead_change"],
    "yacht_turn_transition_zero": _CUE_DURATION_MS["zero"],
    "yacht_game_finish": _GAME_FINISH_CUE_DURATION_MS,
}


# ── §2.4 불변식: 모달이 닫히기 전에 조명이 중립으로 돌아와 있어야 한다 ──────


@pytest.mark.parametrize(("cue_name", "budget"), sorted(_CUE_BUDGETS.items()))
def test_yacht_cue_returns_before_modal_closes(cue_name: str, budget: int):
    """복귀 실패 = 인식 실패다.

    모달이 사라진 순간에 조명이 아직 색을 물고 있으면, 그 상태로 다음 굴림이
    들어와 YOLO가 학습 시점과 다른 색분포를 본다.
    """
    cue = YACHT_CUES[cue_name]

    assert cue.fits_within(
        budget
    ), f"{cue_name}: 복귀까지 {cue.total_ms}ms인데 연출은 {budget}ms에 끝난다"


def test_every_fsm_cue_name_has_a_mapping():
    """FSM이 발행하는 큐 이름과 매핑 키가 어긋나면 조명만 조용히 안 나온다."""
    mapped = set(build_cue_map())

    assert set(_CUE_BUDGETS) <= mapped


def test_roll_time_celebration_never_touches_the_light():
    """굴림 구간은 주사위 인식이 걸린 곳이라 조명이 흔들려선 안 된다.

    yacht_hand_achieved는 화면만 쓰는 연출이다. 매핑에 이름이 없으면 조명이
    그냥 무시하므로, 누군가 "빠진 것 같다"며 채워 넣지 않도록 못을 박는다.
    """
    assert "yacht_hand_achieved" not in build_cue_map()


@pytest.mark.asyncio
async def test_roll_time_cue_sends_no_light_command():
    driver = MockDriver()
    controller = build_controller(LightConfig(driver="mock"))
    controller._driver = driver

    controller.on_message(
        WSMessage(
            msg_type=MsgType.STATE_UPDATE.value,
            payload={"phase": YachtPhase.AWAITING_KEEP.value},
        ),
        game="yacht",
    )
    await _settle()
    driver.applied.clear()

    controller.on_message(
        WSMessage.make_cue("yacht_hand_achieved", {"duration_ms": 2600}), game="yacht"
    )
    await asyncio.sleep(0.3)

    assert driver.applied == [], "굴림 축하가 조명을 건드렸다"


# ── 페이즈 이름 계약 (§3.4 동결 목록) ────────────────────────────────────────


def test_all_frozen_werewolf_phases_are_mapped():
    """동결된 15개 페이즈는 전부 Scene을 가져야 한다.

    빠진 페이즈는 중립 백색으로 폴백되는데, 밤 한복판에서 갑자기 백색 최대가
    되면 연출이 무너진다. 이름이 곧 매핑 키라 이 테스트가 계약을 지킨다.
    """
    scenes = build_scene_map(night_brightness=15)["werewolf"]
    missing = [phase.value for phase in WerewolfPhase if phase.value not in scenes]

    assert missing == []


def test_all_yacht_phases_are_mapped():
    scenes = build_scene_map(night_brightness=15)["yacht"]
    missing = [phase.value for phase in YachtPhase if phase.value not in scenes]

    assert missing == []


# ── 연출 의도 ────────────────────────────────────────────────────────────────


def test_night_starts_in_full_darkness():
    """밤은 암전에서 시작한다. 거기서 각 역할 색이 스며든다."""
    scenes = build_scene_map(night_brightness=15)["werewolf"]

    assert scenes["night_start"].is_blackout


def test_night_phases_stay_dark():
    """밤은 어두워야 밤이다. 밤 페이즈가 밝아지면 낮과 구별되지 않는다."""
    scenes = build_scene_map(night_brightness=15)["werewolf"]
    night_phases = [p.value for p in WerewolfPhase if p.value.startswith("night_")]

    for phase in night_phases:
        assert scenes[phase].brightness <= 15, f"{phase}가 밤답지 않게 밝다"


def test_dawn_is_the_brightest_and_slowest_transition():
    """밤→낮이 이 게임의 감정적 클라이막스다.

    프론트 PhaseTransition의 dawn 타입(duration 2500)과 타이밍을 맞춘다.
    """
    scenes = build_scene_map(night_brightness=15)["werewolf"]
    dawn = scenes["day_discussion"]

    assert dawn.brightness == 100
    assert dawn.transition_ms == 2500


def test_night_brightness_is_tunable():
    """현장에서 실물로 찾아야 하는 값이라 매 페이즈를 고치지 않고 돌릴 수 있어야 한다."""
    dim = build_scene_map(night_brightness=3)["werewolf"]
    bright = build_scene_map(night_brightness=30)["werewolf"]

    assert dim["night_werewolf"].brightness == 3
    assert bright["night_werewolf"].brightness == 30
    # 암전은 밤 밝기와 무관하게 항상 완전한 어둠이다.
    assert bright["night_start"].is_blackout


def test_all_yacht_scenes_are_neutral():
    """요트는 Scene이 항상 중립이고 Cue만 일시적으로 벗어난다.

    종료도 예외가 아니다. Scene을 금색으로 두면 축하가 끝나지 않고 그 색에
    머무르고, Cue와 색이 같아 중복 제거에 걸려 연출이 통째로 사라진다.
    """
    scenes = build_scene_map(night_brightness=15)["yacht"]

    for phase in YachtPhase:
        assert scenes[phase.value] == NEUTRAL_SCENE, f"{phase.value}가 중립이 아니다"


@pytest.mark.parametrize("cue_name", IN_PLAY_YACHT_CUES)
def test_in_play_yacht_cues_keep_luminance(cue_name: str):
    """요트 연출은 색을 갈아엎지 않고 톤만 얹는다.

    이 전구가 곧 주사위 인식 조명이라 원색이 들어오면 YOLO가 학습 시점과 다른
    색분포를 본다. 밝기는 고정하고 채도만 낮게 유지해 광량을 지킨다.
    연출의 세기는 조명이 아니라 화면 모달이 감당한다.
    """
    cue = YACHT_CUES[cue_name]

    assert cue.brightness == 100, "요트에서 광량이 흔들리면 그대로 인식 위험이다"
    # 가장 어두운 채널이 충분히 높아야 원색이 아니라 틴트다.
    assert min(cue.color) >= 130, f"{cue_name} 채도가 높아 색분포를 흔든다: {cue.color}"


def test_game_finish_cue_may_use_full_color():
    """게임이 끝나면 더 굴릴 주사위가 없으므로 인식 제약에서 자유롭다."""
    finish = YACHT_CUES["yacht_game_finish"]

    assert min(finish.color) < 130


# ── 통합: 기본 설정으로 조립된 컨트롤러 ──────────────────────────────────────


async def _settle() -> None:
    for _ in range(10):
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_default_controller_plays_werewolf_night():
    driver = MockDriver()
    controller = build_controller(LightConfig(driver="mock"))
    controller._driver = driver

    controller.on_message(
        WSMessage(msg_type=MsgType.STATE_UPDATE.value, payload={"phase": "night_start"}),
        game="werewolf",
    )
    await _settle()
    assert driver.last[1] == 0

    controller.on_message(
        WSMessage(msg_type=MsgType.STATE_UPDATE.value, payload={"phase": "night_werewolf"}),
        game="werewolf",
    )
    await _settle()
    color, brightness, _ = driver.last
    assert color[0] > color[1] and color[0] > color[2], "늑대인간 밤은 붉어야 한다"
    assert 0 < brightness <= 15


@pytest.mark.asyncio
async def test_highlight_cue_variant_is_selected():
    """야찌·라지스트레이트는 강조 변형으로 갈라진다."""
    driver = MockDriver()
    controller = build_controller(LightConfig(driver="mock"))
    controller._driver = driver

    controller.on_message(
        WSMessage.make_cue(
            "yacht_turn_transition",
            {"variant": "highlight", "duration_ms": _CUE_DURATION_MS["highlight"]},
        ),
        game="yacht",
    )
    await _settle()

    assert driver.last[0] == YACHT_CUES["yacht_turn_transition_highlight"].color


@pytest.mark.asyncio
async def test_game_end_celebrates_then_returns_to_default():
    """축하 조명이 실제로 터지고, 끝나면 기본색으로 돌아온다.

    Scene을 금색으로 두면 Cue와 색이 같아 중복 제거에 걸려 전구에 나가는
    명령이 Scene 하나뿐이 된다 — 축하가 통째로 사라진다.
    """
    driver = MockDriver()
    controller = build_controller(LightConfig(driver="mock"))
    controller._driver = driver

    controller.on_message(
        WSMessage(
            msg_type=MsgType.STATE_UPDATE.value,
            payload={"phase": YachtPhase.AWAITING_SCORE.value},
        ),
        game="yacht",
    )
    await _settle()
    driver.applied.clear()

    controller.on_message(
        WSMessage(
            msg_type=MsgType.STATE_UPDATE.value, payload={"phase": YachtPhase.GAME_END.value}
        ),
        game="yacht",
    )
    controller.on_message(
        WSMessage.make_cue("yacht_game_finish", {"duration_ms": _GAME_FINISH_CUE_DURATION_MS}),
        game="yacht",
    )
    await asyncio.sleep(4.0)

    colors = [applied[0] for applied in driver.applied]
    assert YACHT_CUES["yacht_game_finish"].color in colors, "축하 조명이 나가지 않았다"
    assert driver.last[0] == NEUTRAL_SCENE.color, "축하 후 기본색으로 안 돌아왔다"


@pytest.mark.asyncio
async def test_normal_cue_falls_back_to_base_variant():
    driver = MockDriver()
    controller = build_controller(LightConfig(driver="mock"))
    controller._driver = driver

    controller.on_message(
        WSMessage.make_cue(
            "yacht_turn_transition",
            {"variant": "normal", "duration_ms": _CUE_DURATION_MS["normal"]},
        ),
        game="yacht",
    )
    await _settle()

    assert driver.last[0] == YACHT_CUES["yacht_turn_transition"].color
