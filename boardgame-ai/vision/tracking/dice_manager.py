"""주사위 트래킹 이력 관리 및 DiceState 조립.

ByteTracker가 track_id를 유지하고,
DiceManager는 track_id별 motion_score / stable_frames / pip_count를 관리.
"""

from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any

from vision.detectors.dot_counter import DotCounter
from vision.schemas import YoloDet
from vision.yacht.schemas import DiceState


@dataclass
class _DiceHistory:
    """track_id별 이력."""

    center_history: deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=10))
    pip_buffer: deque[int] = field(default_factory=lambda: deque(maxlen=5))
    stable_frames: int = 0
    last_pip: int | None = None
    miss_count: int = 0  # tracked에서 빠진 연속 프레임 수 (가림 시 history 보존용)


class DiceManager:
    """
    Parameters
    ----------
    motion_threshold : 주사위 정지 판정 기준 (정규화 center 이동 표준편차)
    stabilization_frames : stable로 확정하기 위한 최소 프레임 수
    history_window : motion_score 계산용 이력 윈도우 크기
    pip_buffer_size : pip_count 다수결 버퍼 크기
    history_max_miss : tracked에서 사라진 후 history를 유지할 최대 프레임 수
                       (ByteTracker.max_age와 동일 정책 — 일시 가림 후 재매칭 시 pip 유지)
    """

    def __init__(
        self,
        motion_threshold: float = 0.002,
        stabilization_frames: int = 15,
        history_window: int = 10,
        pip_buffer_size: int = 11,  # 더 큰 버퍼로 YOLO/Hough 끊김 흡수
        history_max_miss: int = 30,
        relative_motion_threshold: float = 0.12,
    ) -> None:
        # 정지 판정 기준: 프레임당 이동이 주사위 크기의 이 비율 미만이면 정지.
        # 0.12 — 이웃과 붙은 박스는 좌우 ±3px(70px 주사위에서 프레임 간 8~10%)씩
        # 떨린다. 굴러가는 주사위는 프레임마다 30% 넘게 움직여 충분히 갈린다.
        # motion_threshold(정규화 좌표 절대값)는 호환용으로만 남는다 — 화면 속
        # 주사위 크기와 무관한 고정값이라, 카메라 높이가 바뀌면 의미가 달라진다.
        self._relative_motion = relative_motion_threshold
        self._motion_threshold = motion_threshold
        self._stabilization_frames = stabilization_frames
        self._history_window = history_window
        self._pip_buffer_size = pip_buffer_size
        self._history_max_miss = history_max_miss
        self._histories: dict[int, _DiceHistory] = {}

    def update(
        self,
        tracked: list[tuple[int, YoloDet]],
        frame_bgr: Any,
        dot_counter: DotCounter,
    ) -> list[DiceState]:
        """
        Parameters
        ----------
        tracked   : ByteTracker.update() 결과 [(track_id, YoloDet), ...]
        frame_bgr : 원본 BGR 프레임 (DotCounter 호출용)
        dot_counter : DotCounter 인스턴스

        Returns
        -------
        list[DiceState] — 현재 프레임의 모든 추적 주사위 상태
        """
        active_ids = {tid for tid, _ in tracked}

        # tracked에 없는 history는 즉시 지우지 않고 miss_count 누적.
        # 손에 가려졌다가 같은 track_id로 돌아올 수 있으므로 max_miss 동안 유지.
        for tid, hist in list(self._histories.items()):
            if tid not in active_ids:
                hist.miss_count += 1
                if hist.miss_count > self._history_max_miss:
                    del self._histories[tid]

        states: list[DiceState] = []

        for track_id, det in tracked:
            hist = self._histories.setdefault(
                track_id,
                _DiceHistory(
                    center_history=deque(maxlen=self._history_window),
                    pip_buffer=deque(maxlen=self._pip_buffer_size),
                ),
            )

            hist.miss_count = 0  # 다시 잡힘 — 가림 카운터 리셋

            center = det.bbox.center()
            box_w, box_h = det.bbox.x2 - det.bbox.x1, det.bbox.y2 - det.bbox.y1
            jumped = False
            if hist.center_history and box_w > 0 and box_h > 0:
                px, py = hist.center_history[-1]
                step = (((center[0] - px) / box_w) ** 2 + ((center[1] - py) / box_h) ** 2) ** 0.5
                # 한 번에 주사위 크기의 절반 넘게 옮겨졌다 = 다른 자리에 놓였다.
                # 컵에 가려졌다 같은 track_id로 딴 곳에서 다시 잡히는 경우가 이렇다.
                # 박스 떨림은 이만큼 안 된다. 이력을 새로 시작해 정지부터 다시 잰다.
                if step > _JUMP_RATIO:
                    hist.center_history.clear()
                    jumped = True
            hist.center_history.append(center)

            motion_score = _compute_motion_score(hist.center_history, box_w, box_h)
            is_stable = not jumped and motion_score < self._relative_motion

            if is_stable:
                hist.stable_frames += 1
            else:
                if hist.stable_frames > 0 or hist.last_pip is not None:
                    # 움직이기 시작했다 = 굴렸거나 옮겼다. 앞 면의 표를 버린다.
                    #
                    # 안 버리면 같은 track_id로 이어진 주사위는 옛 면의 표(최대
                    # 11표)가 새 면의 표를 이긴다. 굴림 확정은 정지 15프레임에서
                    # 나는데 눈 세기는 정지 10프레임부터라, 확정 순간 새 표는
                    # 5개 남짓이다 — 옛 눈이 그대로 굴림 결과로 나간다.
                    #
                    # 확정값도 지운다. 새 면이 아직 안 읽혔으면 "?"(수동 입력)가
                    # 나가는 편이 옛 눈이 조용히 나가는 것보다 낫다.
                    hist.pip_buffer.clear()
                    hist.last_pip = None
                hist.stable_frames = 0

            # stable 확정 구간에서만 pip_count 갱신.
            # 채택 조건 (모두 만족):
            #   1) 1위 표수 ≥ 3 (단발 오인식 차단)
            #   2) 1위 표수 ≥ 버퍼의 1/3 (희박한 분포 차단)
            #   3) 1위가 2위보다 ≥2표 우세 (비등 분포면 보류 — 같은 dice에서
            #      두 값이 비등하게 나오면 인식이 흔들리는 중이므로 갱신 보류)
            # 원래 과반(>n/2) 조건은 None이 자주 섞이는 케이스에서 last_pip이
            # 영영 갱신 안 되던 문제가 있어, 절대 표수 + 마진 기준으로 대체.
            if hist.stable_frames >= self._stabilization_frames:
                pip = dot_counter.count(frame_bgr, det.bbox)
                if pip is not None:
                    hist.pip_buffer.append(pip)
                    top = Counter(hist.pip_buffer).most_common(2)
                    if top:
                        candidate, votes = top[0]
                        runner_up_votes = top[1][1] if len(top) > 1 else 0
                        min_votes = max(3, len(hist.pip_buffer) // 3)
                        margin_ok = (votes - runner_up_votes) >= 2
                        if votes >= min_votes and margin_ok:
                            hist.last_pip = candidate
            else:
                # 흔들리는 프레임 → 직전 stable 값 유지
                pass

            states.append(
                DiceState(
                    track_id=track_id,
                    bbox=det.bbox,
                    center=center,
                    motion_score=motion_score,
                    stable_frames=hist.stable_frames,
                    pip_count=hist.last_pip,
                )
            )

        return states

    def reset(self) -> None:
        self._histories.clear()


# 한 프레임 이동이 주사위 크기의 이 비율을 넘으면 "옮겨졌다"로 본다.
_JUMP_RATIO = 0.5


def _compute_motion_score(
    history: deque[tuple[float, float]], box_w: float, box_h: float
) -> float:
    """최근 프레임당 이동량의 중앙값 — 주사위 크기 단위.

    0.12이면 프레임마다 주사위 크기의 12%씩 움직이고 있다는 뜻이다.

    예전에는 이동량의 **표준편차**를 썼다. 그러면 일정한 속도로 미끄러지는
    주사위는 정지로, 제자리에서 박스만 떨리는 주사위(이웃 주사위와 붙어 YOLO
    박스가 흔들리는 경우)는 움직임으로 판정됐다 — 그 주사위는 영영 눈을 세지
    않아 "?"로 남았다(2026-11-11 실물 화면).

    중앙값을 쓰는 이유: 박스가 한두 프레임 크게 튀어도 정지가 깨지지 않는다.
    샘플이 부족하면 큰 값을 반환해 가짜 stable 판정을 막는다.
    """
    if len(history) < 5 or box_w <= 0 or box_h <= 0:
        return float("inf")
    pts = list(history)[-6:]
    steps = sorted(
        ((pts[i][0] - pts[i - 1][0]) / box_w) ** 2 + ((pts[i][1] - pts[i - 1][1]) / box_h) ** 2
        for i in range(1, len(pts))
    )
    return steps[len(steps) // 2] ** 0.5
