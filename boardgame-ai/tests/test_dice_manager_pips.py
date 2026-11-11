"""주사위가 다시 움직이면 앞 면의 눈 표를 버린다."""

from __future__ import annotations

from vision.schemas import BBox, YoloDet
from vision.tracking.dice_manager import DiceManager


class _FixedCounter:
    def __init__(self) -> None:
        self.value = 2

    def count(self, _frame, _bbox):
        return self.value


def _det(cx: float) -> YoloDet:
    return YoloDet(bbox=BBox(cx - 0.02, 0.48, cx + 0.02, 0.52, 0.9, "dice"), cls_name="dice")


def _run(mgr, counter, cx, frames):
    state = None
    for _ in range(frames):
        state = mgr.update([(1, _det(cx))], None, counter)[0]
    return state


def test_reroll_with_same_track_id_reports_new_face() -> None:
    mgr = DiceManager(stabilization_frames=3)
    counter = _FixedCounter()
    assert _run(mgr, counter, 0.3, 20).pip_count == 2

    # 같은 track_id로 굴러간다 (위치 크게 이동) → 새 면은 5
    for step in range(6):
        mgr.update([(1, _det(0.3 + 0.05 * step))], None, counter)
    counter.value = 5
    # 굴림 확정 시점(정지 후 몇 프레임) — 옛 눈 2가 나가면 안 된다
    # 정지 판정은 최근 10프레임 이동량을 본다(history_window) → 그만큼 + 정지 3 + 표 5
    state = _run(mgr, counter, 0.6, 10 + 3 + 5)
    assert state.pip_count == 5


def test_moving_die_has_no_stale_pip() -> None:
    mgr = DiceManager(stabilization_frames=3)
    counter = _FixedCounter()
    _run(mgr, counter, 0.3, 20)
    state = mgr.update([(1, _det(0.45))], None, counter)[0]
    assert state.pip_count is None


def test_jittering_box_still_counts_as_stable() -> None:
    """이웃과 붙어 박스가 몇 픽셀씩 떨려도 정지로 본다 — 안 그러면 영영 "?"."""
    mgr = DiceManager(stabilization_frames=3)
    counter = _FixedCounter()
    state = None
    for i in range(30):
        jitter = 0.002 if i % 2 else -0.002  # 박스 폭 0.04의 5%
        state = mgr.update([(1, _det(0.3 + jitter))], None, counter)[0]
    assert state.stable_frames > 10
    assert state.pip_count == 2


def test_steady_slide_is_not_stable() -> None:
    """일정한 속도로 미끄러지는 주사위는 정지가 아니다 (예전 표준편차 기준의 구멍)."""
    mgr = DiceManager(stabilization_frames=3)
    counter = _FixedCounter()
    state = None
    for i in range(20):
        state = mgr.update([(1, _det(0.2 + 0.006 * i))], None, counter)[0]
    assert state.stable_frames == 0


def test_jump_to_new_spot_drops_old_pip() -> None:
    """컵에 가려졌다 같은 track_id로 딴 곳에서 다시 잡혀도 옛 눈을 내지 않는다."""
    mgr = DiceManager(stabilization_frames=3)
    counter = _FixedCounter()
    _run(mgr, counter, 0.3, 20)
    state = mgr.update([(1, _det(0.6))], None, counter)[0]
    assert state.pip_count is None
