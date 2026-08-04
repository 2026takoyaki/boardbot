"""개발 모드 — 플래그가 꺼지면 아무것도 열리지 않아야 한다."""

from __future__ import annotations

import math

import pytest

from backend.dev import (
    DEV_ENV_VAR,
    is_dev_mode,
    roll_dice,
    seat_registration_events,
    synthetic_seat_zone,
)
from core.constants import CommonEventType
from core.models import SeatZone


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv(DEV_ENV_VAR, raising=False)


# ── 플래그 ───────────────────────────────────────────────────────────────────


def test_dev_mode_is_off_by_default():
    """켜는 걸 잊는 것보다 끄는 걸 잊는 게 훨씬 위험하다."""
    assert is_dev_mode() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_dev_mode_accepts_common_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv(DEV_ENV_VAR, value)

    assert is_dev_mode() is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "아무말"])
def test_anything_else_leaves_dev_mode_off(monkeypatch, value):
    monkeypatch.setenv(DEV_ENV_VAR, value)

    assert is_dev_mode() is False


# ── 가짜 좌석 ────────────────────────────────────────────────────────────────


def test_synthetic_seats_are_spread_around_the_table():
    """좌석이 겹치면 좌석 매칭이 서로를 구분하지 못한다."""
    seats = [synthetic_seat_zone(i, 4) for i in range(4)]
    positions = [s.body_xy for s in seats]

    for i, a in enumerate(positions):
        for b in positions[i + 1 :]:
            distance = math.dist(a, b)
            assert distance > 0.2, f"좌석이 너무 붙어 있다: {a} {b}"


def test_synthetic_seat_survives_serialization():
    """실제 등록과 같은 경로를 타려면 SeatZone.from_dict를 통과해야 한다."""
    seat = synthetic_seat_zone(0, 3)

    restored = SeatZone.from_dict(seat.to_dict())

    assert restored.posture == seat.posture
    assert restored.right_arm.handedness == "Right"
    assert restored.left_arm.handedness == "Left"


def test_seat_events_use_the_real_registration_event():
    """지름길을 따로 파면 개발에서 되던 게 실전에서 안 된다."""
    events = seat_registration_events(["p1", "p2"])

    assert [e.event_type for e in events] == [CommonEventType.SEAT_REGISTERED.value] * 2
    assert [e.actor_id for e in events] == ["p1", "p2"]
    for event in events:
        # orchestrator가 실제 등록과 구분하지 못해야 한다.
        SeatZone.from_dict(event.data["seat_zone"])


def test_seat_events_are_empty_without_players():
    assert seat_registration_events([]) == []


# ── 주사위 ───────────────────────────────────────────────────────────────────


def test_roll_returns_five_legal_dice():
    values = roll_dice()

    assert len(values) == 5
    assert all(1 <= v <= 6 for v in values)


def test_kept_dice_survive_the_reroll():
    previous = [1, 2, 3, 4, 5]

    values = roll_dice(keep_mask=[True, False, True, False, True], previous=previous)

    assert values[0] == 1
    assert values[2] == 3
    assert values[4] == 5


def test_roll_tolerates_missing_previous_values():
    """keep이 켜져 있어도 이전 값이 없으면 그냥 새로 굴린다."""
    values = roll_dice(keep_mask=[True] * 5, previous=[])

    assert len(values) == 5
    assert all(1 <= v <= 6 for v in values)
