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
    NEUTRAL_SCENE,
    YACHT_CUES,
    build_cue_map,
    build_scene_map,
)
from core.constants import MsgType
from core.envelope import WSMessage
from games.werewolf.ontology import WerewolfPhase
from games.yacht.fsm import (
    _GAME_FINISH_CUE_DURATION_MS,
    _HIGHLIGHT_CUE_DURATION_MS,
    _TURN_CUE_DURATION_MS,
)
from games.yacht.state import YachtPhase

# FSM이 발행하는 큐 이름 → 그 큐가 싣고 오는 duration_ms.
# 이 대응이 어긋나면 조명이 모달보다 늦게 복귀한다.
_CUE_BUDGETS = {
    "yacht_turn_transition": _TURN_CUE_DURATION_MS,
    "yacht_turn_transition_highlight": _HIGHLIGHT_CUE_DURATION_MS,
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

    assert cue.fits_within(budget), (
        f"{cue_name}: 복귀까지 {cue.total_ms}ms인데 연출은 {budget}ms에 끝난다"
    )


def test_every_fsm_cue_name_has_a_mapping():
    """FSM이 발행하는 큐 이름과 매핑 키가 어긋나면 조명만 조용히 안 나온다."""
    mapped = set(build_cue_map())

    assert set(_CUE_BUDGETS) <= mapped


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
    """"밤이 되었습니다"는 암전에서 시작한다. 거기서 각 역할 색이 스며든다."""
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


def test_yacht_scenes_are_all_neutral_except_game_end():
    """요트는 Scene이 항상 중립이고 Cue만 일시적으로 벗어난다."""
    scenes = build_scene_map(night_brightness=15)["yacht"]
    recognition_phases = [
        YachtPhase.AWAITING_ROLL,
        YachtPhase.AWAITING_KEEP,
        YachtPhase.AWAITING_SCORE,
    ]

    for phase in recognition_phases:
        assert scenes[phase.value] == NEUTRAL_SCENE, f"{phase.value}는 인식 구간이다"


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
            {"is_highlight": True, "duration_ms": _HIGHLIGHT_CUE_DURATION_MS},
        ),
        game="yacht",
    )
    await _settle()

    assert driver.last[0] == YACHT_CUES["yacht_turn_transition_highlight"].color


@pytest.mark.asyncio
async def test_normal_cue_falls_back_to_base_variant():
    driver = MockDriver()
    controller = build_controller(LightConfig(driver="mock"))
    controller._driver = driver

    controller.on_message(
        WSMessage.make_cue(
            "yacht_turn_transition",
            {"is_highlight": False, "duration_ms": _TURN_CUE_DURATION_MS},
        ),
        game="yacht",
    )
    await _settle()

    assert driver.last[0] == YACHT_CUES["yacht_turn_transition"].color
