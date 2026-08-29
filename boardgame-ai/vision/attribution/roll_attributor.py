"""굴린 플레이어 결정 (RollAttributor) — 손 점유 + roll_tray 진입 게이트 기반.

상태머신:
  WAITING
   │  손(wrist 또는 5 fingertip 중 하나)이 tray bbox에 들어옴 → HAND_IN_TRAY
   │  진입 시점에 snapshot 저장 (직전 마지막 stable dice 좌표/pip)
   ↓
  HAND_IN_TRAY (점유 중)
   │  매 프레임 nearest player_id 누적, roll_tray가 tray 안에 진입한 프레임 카운트
   │  종료 조건: 손 모두 tray 밖 + dice 모두 stable + snapshot 대비 변화 점수 임계 통과
   │             + roll_tray 진입 누적 ≥ 임계 (= 굴림통이 실제로 사용됨)
   │    → ROLL_CONFIRMED 발화 → WAITING
   │  하나라도 미달 → 발화 없이 WAITING (손만 댄 / 킵존 옮김 등)
   ↓
  WAITING

킵존 처리:
  현재는 tray_inner를 직접 참조하지 않고, roll_tray 진입 게이트로 굴림/킵존 옮김을 구분.
  ROLL_CONFIRMED data의 keep_mask는 전부 False (모든 dice가 굴림 대상).
"""

from __future__ import annotations

import logging
from collections import Counter, deque
from dataclasses import dataclass
from enum import Enum, auto

from vision.schemas import BBox, HandDet
from vision.yacht.schemas import DiceState, YachtFramePerception

# 디버그 로그용 — pipeline에서 logging.basicConfig(level=DEBUG)로 켤 수 있음.
# 기본 INFO/WARNING 환경에선 조용히 동작.
_log = logging.getLogger(__name__)


class RollState(Enum):
    WAITING = auto()
    HAND_IN_TRAY = auto()


@dataclass
class _DiceSnapshot:
    """점유 시작 시점의 굴림 대상 dice 스냅샷."""

    items: dict[int, tuple[tuple[float, float], int | None]]
    # track_id → (center, pip_count)


class RollAttributor:
    """
    Parameters
    ----------
    stabilization_frames    : dice 안정 판정 임계 (이 만큼 stable_frames 도달해야 안정)
    grab_fallback_window_frames : nearest player_id 누적 윈도우
    expected_dice_count     : 굴림 후 모두 보여야 할 dice 총 개수 (요트 5개)
    change_score_threshold  : snapshot 대비 변화 비율 임계 (이상이면 굴림으로 인정)
    center_shift_ratio      : center 이동을 "변화"로 판정하는 박스 변길이 대비 비율
    tray_pad                : 손이 tray 진입했다고 볼 패딩 (정규화)
    """

    def __init__(
        self,
        stabilization_frames: int = 30,
        grab_fallback_window_frames: int = 60,
        expected_dice_count: int = 5,
        change_score_threshold: float = 0.15,
        center_shift_ratio: float = 0.2,
        tray_pad: float = 0.02,
        enter_debounce_frames: int = 3,
        exit_debounce_frames: int = 3,
        roll_tray_overlap_ratio: float = 0.05,
        roll_tray_in_tray_required: int = 3,
        # 호환용 — 더 이상 사용하지 않지만 기존 호출자 깨지지 않도록 유지
        roll_lift_threshold: float = 0.02,
        motion_threshold: float = 0.002,
    ) -> None:
        self._stab_frames = stabilization_frames
        self._fallback_window = grab_fallback_window_frames
        self._expected_dice = expected_dice_count
        self._change_threshold = change_score_threshold
        self._center_shift_ratio = center_shift_ratio
        self._tray_pad = tray_pad
        self._enter_debounce = enter_debounce_frames
        self._exit_debounce = exit_debounce_frames
        self._roll_tray_overlap_ratio = roll_tray_overlap_ratio
        self._roll_tray_in_tray_required = roll_tray_in_tray_required
        # 미사용 (인터페이스 호환만 유지)
        _ = roll_lift_threshold
        _ = motion_threshold

        self._state = RollState.WAITING
        self._candidate_actor: str | None = None
        self._snapshot: _DiceSnapshot | None = None
        # WAITING 동안 마지막으로 확보한 안정 snapshot. 손이 dice를 가린 후의 흐트러진
        # 좌표가 아니라, 손 들어가기 직전 진짜 안정 상태를 비교 기준으로 사용한다.
        self._last_stable_snapshot: _DiceSnapshot | None = None
        # 직전 update()에서 굴림이 finalize됐는지 (actor가 None이어도 True 가능).
        # pipeline이 perception.roll_just_confirmed 게이트 세팅에 사용.
        self._just_finalized: bool = False

        # 디바운스 카운터: 손 안에 있는 연속 프레임, 밖에 있는 연속 프레임
        self._in_streak: int = 0
        self._out_streak: int = 0

        # roll_tray가 tray 안에 진입한 프레임 누적 — HAND_IN_TRAY 동안에만 카운트.
        # 이 누적이 임계 이상일 때만 ROLL_CONFIRMED 발화. "굴림통이 실제로 사용됨"의 신호.
        self._roll_tray_in_tray_streak: int = 0

        # HAND_IN_TRAY 동안 손이 실제로 tray 안에 한 번이라도 잡혔는지.
        # shaking 신호만으로 진입한 경우(예: dice를 굴림통에 담느라 굴림통만
        # tray 위에서 흔드는 동작) finalize를 차단하기 위한 가드.
        # 가장자리 굴림 자세에서도 손가락 끝/MCP 중 어느 하나는 보통 tray bbox에
        # 떨어지므로 진짜 굴림은 통과한다.
        self._hand_seen_in_tray: bool = False

        # nearest player 누적 — fallback actor 산정용 (state 무관, 매 프레임)
        self._fallback_buf: deque[str | None] = deque(maxlen=grab_fallback_window_frames)
        # roll_tray가 tray 안에 있는 동안만 누적되는 nearest 버퍼 —
        # 실제 굴림통과 함께 움직이는 손의 player_id가 최빈으로 잡힘.
        # 이게 1순위 actor 산정 근거. HAND_IN_TRAY 진입 시 매번 초기화하고,
        # player_id가 잡힌 프레임(None 아님)만 누적해 다수결 통계가 흐려지지 않게 한다.
        self._roll_actor_buf: deque[str] = deque(maxlen=grab_fallback_window_frames)

        # roll_tray center 이력 — 굴림통이 실제로 흔들리는지 판정용.
        # tray 가장자리에서 손가락 한 두 마디만 진입한 채 굴리는 자세에선
        # 손 landmark가 tray bbox에 안 떨어져 점유가 안 잡히는데, 굴림통 자체는
        # 사람이 잡고 흔들기 때문에 center가 움직인다. 그 움직임을 점유 트리거의
        # 보조 신호로 사용한다 (정적으로 놓여있는 roll_tray는 움직임 0이라 false
        # positive 없음).
        self._roll_tray_center_hist: deque[tuple[float, float]] = deque(maxlen=10)

    # ── public ───────────────────────────────────────────────────────────────

    def update(
        self,
        perception: YachtFramePerception,
        active_player: str | None = None,
    ) -> str | None:
        """매 프레임 호출. ROLL_CONFIRMED 발화 시 actor 반환, 아니면 None.

        actor는 active_player 필터 없이 "실제로 굴린(roll_tray에 손이 가장
        가까웠던) 사람"으로 잡는다. 차례가 아닌 사람이 굴려도 그 사람의
        player_id가 actor로 반환되어 FSM이 차례 위반을 감지할 수 있다.
        active_player 인자는 인터페이스 호환을 위해 남겨두되 사용하지 않는다.
        """
        _ = active_player
        self._just_finalized = False  # 매 프레임 리셋 — 발화 분기에서만 True

        # nearest player_id 누적 (tray 또는 roll_tray 근처) — fallback actor용.
        # actor 판정에는 active_player 필터를 걸지 않는다: 차례가 아닌 사람이
        # 굴린 경우에도 그 사람을 actor로 잡아야 FSM이 차례 위반을 감지한다.
        nearest = self._nearest_player_to_tray(perception, active_player=None)
        self._fallback_buf.append(nearest)

        # roll_tray center 이력 갱신 — 점유 트리거의 보조 신호 (흔들림 감지).
        # tray와 roll_tray가 모두 보일 때만 의미 있음. 둘 중 하나라도 사라지면
        # 이력을 비워, 다시 보였을 때 끊긴 시점의 좌표가 가짜 움직임으로
        # 누적되지 않도록 한다.
        if perception.tray is not None and perception.roll_tray is not None:
            self._roll_tray_center_hist.append(perception.roll_tray.center())
        else:
            self._roll_tray_center_hist.clear()

        # 디바운스 카운터 갱신.
        # 점유 인정 조건 (OR):
        #   1) 손/손가락/MCP가 tray 패딩 영역 안에 있다 (정상 굴림 자세)
        #   2) roll_tray가 tray와 겹친 채로 흔들리고 있다
        #      — 트레이 가장자리에서 굴림통 끝만 잡고 흔들 때
        #        손 landmark가 tray bbox에 안 떨어지는 자세 커버.
        # 점유 판정·actor 판정 모두 active_player 필터를 걸지 않는다.
        # actor를 무필터로 잡아야 차례가 아닌 사람의 굴림도 그 사람 player_id로
        # 잡혀 FSM이 차례 경고를 띄울 수 있다.
        hand_in_any = self._is_any_hand_in_tray(perception, active_player=None)
        roll_tray_shaking = self._is_roll_tray_shaking(perception)
        if hand_in_any or roll_tray_shaking:
            self._in_streak += 1
            self._out_streak = 0
        else:
            self._out_streak += 1
            self._in_streak = 0
        # finalize 가드용 갱신: 점유 중 어떤 손이든 실제 tray 안에 한 번이라도
        # 잡혔는지. 점유 진입/이탈 판정과 동일하게 active_player 필터를 풀어 검사한다.
        # player_id 다수결이 굳기 전(굴림처럼 짧은 동작)엔 손에 player_id가 안
        # 붙어 있어, 필터를 켜면 정상 굴림인데도 가드가 영원히 안 풀려 finalize가
        # 막히는 데드락이 생긴다. 이 가드의 목적은 "손이 한 번도 tray 안에 안
        # 들어온 shaking 단독(담기) 동작" 차단이므로 무필터로 충분하다.
        if self._state == RollState.HAND_IN_TRAY and hand_in_any:
            self._hand_seen_in_tray = True

        if self._state == RollState.WAITING:
            return self._step_waiting(perception)
        # HAND_IN_TRAY
        return self._step_hand_in_tray(perception)

    @property
    def state(self) -> RollState:
        return self._state

    @property
    def just_finalized(self) -> bool:
        """직전 update()에서 굴림이 finalize 됐는지. actor가 None이어도 True 가능."""
        return self._just_finalized

    # ── 상태별 step ───────────────────────────────────────────────────────────

    def _step_waiting(
        self,
        perception: YachtFramePerception,
    ) -> str | None:
        if perception.tray is None:
            return None
        # 손이 안 잡힌 동안에는 마지막 stable snapshot 갱신.
        # 굴림 대상 dice 모두 stable이면 그 시점을 비교 기준으로 들고 있는다.
        # 매 stable 프레임마다 덮어쓴다: 직전 굴림 직후 새 안정 상태가 다음 굴림의
        # 비교 기준이 되도록 함. 개수만 비교하던 이전 로직은 같은 5개 dice가
        # 위치만 바뀐 경우 stale snapshot이 영구히 남아 2회차부터 변화 점수가
        # 항상 1.0 또는 0.0에 갇혀 발화가 불안정해지는 문제가 있었음.
        if self._out_streak > 0:
            target = self._dice_outside_keep(perception)
            if target and all(d.stable_frames >= self._stab_frames for d in target):
                prev_size = (
                    len(self._last_stable_snapshot.items)
                    if self._last_stable_snapshot is not None
                    else -1
                )
                self._last_stable_snapshot = _take_snapshot(target)
                if prev_size != len(target):
                    _log.debug(
                        f"[roll] last_stable_snapshot 크기변경 "
                        f"prev={prev_size} new={len(target)} "
                        f"kept={self._n_kept(perception)}"
                    )
        # 진입 디바운스 — 연속 N프레임 안에 있어야 진짜 진입으로 인정
        if self._in_streak >= self._enter_debounce:
            self._enter_hand_in_tray(perception)
        return None

    def _step_hand_in_tray(
        self,
        perception: YachtFramePerception,
    ) -> str | None:
        # 점유 중 candidate_actor를 매 프레임 덮어쓰지 않는다.
        # 앞사람이 tray 옆에 손만 두고 있으면 그쪽이 매 프레임 nearest로 잡혀
        # 진짜 굴리는 사람의 진입 시점 actor를 덮어버리는 오인을 방지.
        # 대신 roll_tray가 tray 안에 들어와 있는 "굴리는 중" 프레임에서만
        # nearest를 별도 버퍼에 누적해 확정 시 최빈값으로 사용한다.
        # actor 누적에는 active_player 필터를 걸지 않는다 — 차례가 아닌 사람이
        # 굴린 경우에도 그 사람의 player_id를 actor로 잡아야 FSM이 차례 경고를
        # 띄울 수 있다. (현재 플레이어 손이 가장 가까우면 자연히 그쪽이 최빈값.)
        if self._is_roll_tray_in_tray(perception):
            self._roll_tray_in_tray_streak += 1
            nearest_roll = self._nearest_player_to_tray(perception, active_player=None)
            # player_id가 잡힌 프레임만 누적 — None을 넣으면 손이 잠깐 안 잡힌
            # 프레임이 통계에 섞여 최빈값이 흐려진다. 잡힌 사람만 모아 다수결.
            if nearest_roll is not None:
                self._roll_actor_buf.append(nearest_roll)

        # 진출 디바운스 — 연속 N프레임 밖이어야 진짜 빠진 걸로 인정
        if self._out_streak < self._exit_debounce:
            return None

        # roll_tray 미진입 — 굴림통 안 썼다고 판정 (킵존 옮김 등)
        if self._roll_tray_in_tray_streak < self._roll_tray_in_tray_required:
            _log.debug(
                f"[roll] hand_out: roll_tray 진입 부족 — "
                f"streak={self._roll_tray_in_tray_streak} "
                f"need={self._roll_tray_in_tray_required} → WAITING (굴림 아님)"
            )
            self._reset_to_waiting()
            return None

        # shaking 신호만으로 진입했고 손은 한 번도 tray 안에 안 잡힌 경우 finalize 차단.
        # 굴림통에 dice를 담는 동작(굴림통만 tray 위에서 흔들리고 손은 굴림통 밖에서
        # dice를 집어넣는 자세)이 가짜 ROLL_CONFIRMED로 발화되는 것을 막는다.
        if not self._hand_seen_in_tray:
            _log.debug(
                "[roll] hand_out: 점유 중 손 미진입 (shaking 단독) → "
                "WAITING (담기 동작 가능성, 굴림 아님)"
            )
            self._reset_to_waiting()
            return None

        # 손이 빠짐 — 굴림 종료 조건 체크
        target_dice = self._dice_outside_keep(perception)
        n_kept = self._n_kept(perception)
        need = self._expected_dice - n_kept
        # 1) 모든 굴림 대상 dice가 보여야 함 (개수 일치)
        if len(target_dice) < need:
            _log.debug(
                f"[roll] hand_out: dice 부족 — got={len(target_dice)} need={need} "
                f"kept={n_kept} (state 유지)"
            )
            return None
        # 2) 모두 stable
        unstable = [
            (d.track_id, d.stable_frames)
            for d in target_dice
            if d.stable_frames < self._stab_frames
        ]
        if unstable:
            _log.debug(f"[roll] hand_out: dice 불안정 — {unstable} (state 유지)")
            return None
        # 3) snapshot 대비 변화 점수
        if self._snapshot is None:
            _log.debug("[roll] hand_out: snapshot 없음 → WAITING 복귀 (발화 없음)")
            self._reset_to_waiting()
            return None
        score = _compute_change_score(self._snapshot, target_dice, self._center_shift_ratio)
        _log.debug(
            f"[roll] hand_out: score={score:.2f} threshold={self._change_threshold:.2f} "
            f"snap_size={len(self._snapshot.items)} cur_size={len(target_dice)} "
            f"rt_streak={self._roll_tray_in_tray_streak}"
        )
        if score >= self._change_threshold:
            # 1순위: roll_tray가 tray 안에 있던 프레임들의 nearest 최빈값
            #        (= 실제 굴림통과 함께 움직인 손의 주인)
            # 2순위: 진입 시점에 잡힌 candidate_actor
            # 3순위: 전체 윈도우 nearest 최빈값 (둘 다 비어있을 때만)
            actor = _mode(self._roll_actor_buf) or self._candidate_actor or self._fallback_actor()
            self._just_finalized = True
            _log.info(
                "[roll] ROLL_CONFIRMED actor=%s (roll_buf_mode=%s candidate=%s fallback=%s)",
                actor,
                _mode(self._roll_actor_buf),
                self._candidate_actor,
                self._fallback_actor(),
            )
            self._reset_to_waiting()
            return actor
        # 변화 없음 — 손만 댄 케이스
        _log.debug("[roll] 변화 부족 → WAITING (손만 댐)")
        self._reset_to_waiting()
        return None

    def _enter_hand_in_tray(
        self,
        perception: YachtFramePerception,
    ) -> None:
        self._state = RollState.HAND_IN_TRAY
        # 이번 점유 동안만의 roll_tray 기준 nearest를 다시 모으기 시작.
        self._roll_actor_buf.clear()
        # 진입 시점에 어떤 손이든 실제 tray 안이면 즉시 True.
        # shaking 단독 진입(굴림통만 흔들리고 손은 tray 밖)이면 False로 시작해,
        # 점유 중 손이 한 번도 tray 안에 안 잡히면 finalize가 차단된다.
        # 점유 판정과 동일하게 active_player 필터는 적용하지 않는다 (player_id
        # 미확정 손도 인정해 finalize 데드락 방지).
        self._hand_seen_in_tray = self._is_any_hand_in_tray(perception, active_player=None)
        # 손이 들어온 직후의 흐트러진 dice 좌표 대신,
        # 손 들어가기 직전 마지막 stable snapshot을 비교 기준으로 사용.
        if self._last_stable_snapshot is not None:
            self._snapshot = self._last_stable_snapshot
        else:
            target = self._dice_outside_keep(perception)
            self._snapshot = _take_snapshot(target)
        # 점유 시점 nearest를 candidate로 우선 채택.
        # actor 판정에는 active_player 필터를 걸지 않는다 — 차례가 아닌 사람이
        # 굴린 경우에도 그 사람을 actor로 잡아야 FSM 차례 경고가 동작한다.
        nearest = self._nearest_player_to_tray(perception, active_player=None)
        if nearest is not None:
            self._candidate_actor = nearest
        n_kept = self._n_kept(perception)
        n_outside = len(self._dice_outside_keep(perception))
        _log.debug(
            f"[roll] WAITING → HAND_IN_TRAY "
            f"snap_size={len(self._snapshot.items) if self._snapshot else 0} "
            f"dice_total={len(perception.dice)} kept={n_kept} outside={n_outside} "
            f"tray_inner={'Y' if perception.tray_inner else 'N'} "
            f"actor={self._candidate_actor}"
        )

    def _reset_to_waiting(self) -> None:
        self._state = RollState.WAITING
        self._snapshot = None
        self._candidate_actor = None
        self._roll_tray_in_tray_streak = 0
        self._roll_actor_buf.clear()
        self._hand_seen_in_tray = False

    # ── 헬퍼 ─────────────────────────────────────────────────────────────────

    def _is_any_hand_in_tray(
        self,
        perception: YachtFramePerception,
        active_player: str | None = None,
    ) -> bool:
        """손의 핵심 landmark(wrist + fingertip + MCP 관절)가 tray 패딩 안에 있는가.

        21 landmark 전부 검사하면 손이 멀리 있어도 한 점이 안에 떨어져 false positive.
        대신 wrist(0) + fingertip(4/8/12/16/20) + finger MCP(5/9/13/17)까지 본다.
        MCP를 추가한 이유: 롤트레이 아래쪽을 잡고 굴리는 자세에서는 손가락 끝이
        오히려 tray 밖에 있고 손바닥(MCP 부근)이 tray 영역 안으로 들어와 있을 수
        있어, fingertip만으로는 진입을 놓친다.

        active_player가 주어지면 그 플레이어의 손만 카운트한다. 옆사람이 굴리는 사이
        손을 트레이 근처에 두어도 점유 상태가 끝나지 않게 만들어 굴림 finalize를 보장.
        """
        tray = perception.tray
        if tray is None or not perception.hands:
            return False
        x1, y1 = tray.x1 - self._tray_pad, tray.y1 - self._tray_pad
        x2, y2 = tray.x2 + self._tray_pad, tray.y2 + self._tray_pad
        # MediaPipe landmark 인덱스
        #   wrist=0, fingertip=4/8/12/16/20, finger MCP=5/9/13/17
        probe_indices = (4, 8, 12, 16, 20, 5, 9, 13, 17)
        for hand in perception.hands:
            if active_player is not None and hand.player_id != active_player:
                continue
            wx, wy = hand.wrist_xy
            if x1 <= wx <= x2 and y1 <= wy <= y2:
                return True
            for idx in probe_indices:
                if idx >= len(hand.landmarks_21):
                    continue
                lx, ly = hand.landmarks_21[idx]
                if x1 <= lx <= x2 and y1 <= ly <= y2:
                    return True
        return False

    def _is_roll_tray_in_tray(self, perception: YachtFramePerception) -> bool:
        """roll_tray bbox가 tray bbox와 충분히 겹치는가.

        겹침 비율 = (교집합 면적) / (roll_tray 면적). 이 비율이 임계 이상이면 굴림통이
        tray 영역에 들어와 있다고 본다. 일부만 들어가도 인정.
        """
        rt = perception.roll_tray
        tray = perception.tray
        if rt is None or tray is None:
            return False
        ix1 = max(rt.x1, tray.x1)
        iy1 = max(rt.y1, tray.y1)
        ix2 = min(rt.x2, tray.x2)
        iy2 = min(rt.y2, tray.y2)
        inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
        rt_area = rt.w * rt.h
        if rt_area <= 0:
            return False
        return (inter / rt_area) >= self._roll_tray_overlap_ratio

    def _is_roll_tray_shaking(self, perception: YachtFramePerception) -> bool:
        """roll_tray가 tray와 겹친 채로 흔들리고 있는가.

        조건:
          - roll_tray ∩ tray 겹침 비율 ≥ _roll_tray_overlap_ratio (= tray 위)
          - 최근 N프레임 center 이동량의 합(=경로 길이)이 roll_tray 짧은 변의
            일정 비율 이상 (= 정적으로 놓여있지 않고 사람이 잡고 흔드는 중)

        트레이 가장자리에서 굴림통 끝만 잡고 굴려 손 landmark가 tray bbox에 안
        떨어지는 자세에서 점유를 잡기 위한 보조 신호. 정적으로 놓인 roll_tray는
        이동량 0이라 false positive 없음.
        """
        rt = perception.roll_tray
        if rt is None or not self._is_roll_tray_in_tray(perception):
            return False
        hist = self._roll_tray_center_hist
        if len(hist) < 3:
            return False
        # 경로 길이 = 연속 프레임 간 center 이동의 합
        path = 0.0
        pts = list(hist)
        for i in range(1, len(pts)):
            dx = pts[i][0] - pts[i - 1][0]
            dy = pts[i][1] - pts[i - 1][1]
            path += (dx * dx + dy * dy) ** 0.5
        # roll_tray 짧은 변의 30% 이상 이동했으면 흔들림으로 본다.
        # YOLO bbox 미세 흔들림(노이즈) 정도로는 못 넘는 임계.
        threshold = min(rt.w, rt.h) * 0.3
        return path >= threshold

    def _dice_outside_keep(self, perception: YachtFramePerception) -> list[DiceState]:
        """굴림 대상 dice — 현재는 tray_inner를 무시하고 모든 dice를 굴림 대상으로 본다.

        tray_inner가 사실상 tray 전체를 덮어 dice가 모두 kept로 분류되던 문제를 회피.
        킵존 ROI는 추후 게임 약속(예: tray 우측 N%)으로 별도 정의 예정.
        """
        return list(perception.dice)

    def _n_kept(self, perception: YachtFramePerception) -> int:
        return 0

    def _nearest_player_to_tray(
        self,
        perception: YachtFramePerception,
        active_player: str | None = None,
    ) -> str | None:
        """roll_tray 또는 tray 중심에 가장 가까운 player_id 보유 손.

        roll_tray(굴림통)는 굴리는 사람만 들고 움직이므로 그게 잡힌 프레임에선
        그쪽을 기준으로 잡아야 앞사람이 tray 옆에 손만 두고 있어도 오인하지 않는다.
        roll_tray가 없을 때만 tray 중심으로 폴백.

        active_player가 주어지면 그 플레이어의 손만 후보. 옆사람이 굴림통/트레이
        근처에 손을 둬도 nearest 후보에 들어가지 않아 actor 오인을 막는다.
        """
        ref = perception.roll_tray or perception.tray
        if ref is None:
            return None
        cx, cy = ref.center()
        best_pid: str | None = None
        best_dist = float("inf")
        for hand in perception.hands:
            if hand.player_id is None:
                continue
            if active_player is not None and hand.player_id != active_player:
                continue
            wx, wy = hand.wrist_xy
            d = ((wx - cx) ** 2 + (wy - cy) ** 2) ** 0.5
            if d < best_dist:
                best_dist = d
                best_pid = hand.player_id
        return best_pid

    def _fallback_actor(self) -> str | None:
        counts = Counter(pid for pid in self._fallback_buf if pid is not None)
        if not counts:
            return None
        return counts.most_common(1)[0][0]


# ── 모듈 헬퍼 ────────────────────────────────────────────────────────────────


def _take_snapshot(dice: list[DiceState]) -> _DiceSnapshot:
    return _DiceSnapshot(items={d.track_id: (d.center, d.pip_count) for d in dice})


def _compute_change_score(
    snapshot: _DiceSnapshot,
    current: list[DiceState],
    center_shift_ratio: float,
) -> float:
    """snapshot 대비 변화 점수 (0.0~1.0). 눈(pip) 분포를 1순위로 본다.

    핵심 설계:
      roll_tray로 dice를 잠깐 가렸다 치우기만 해도 ByteTrack이 track_id를
      재할당하거나 개수가 잠깐 어긋나, track_id 기준 비교는 "변화 없음"인데도
      높은 점수를 내 오발화가 났다. 그래서 track_id에 의존하지 않고 pip 값의
      분포(multiset)를 비교한다 — 가렸다 치우면 눈이 그대로라 분포가 같아
      점수 0, 진짜 굴리면 눈이 바뀐 만큼 점수가 오른다.

    절차:
      1) pip 분포(정렬된 multiset)가 다르면 → 바뀐 눈의 개수 비율을 점수로.
      2) pip 분포가 같으면 → **좌표로 짝을 지어** 자리가 바뀐 주사위를 센다.
         가렸다 치우기는 전부 제자리라 짝이 다 맞아 0, 같은 눈이 다시 나온
         재굴림은 그 주사위만 짝지을 자리가 없어 이동으로 남는다.
    """
    if not current:
        return 0.0
    # snapshot이 비어있으면 (점유 시작 시 dice 미감지) 비교 불가 → 0.
    # 과거엔 1.0(무조건 변화)이었으나, 손/roll_tray가 dice를 가린 채 진입한
    # 경우에도 1.0이 나와 가렸다 치우기가 오발화됐다.
    if not snapshot.items:
        return 0.0

    prev_pips = sorted(p for _, p in snapshot.items.values() if p is not None)
    cur_pips = sorted(d.pip_count for d in current if d.pip_count is not None)

    # 1) pip 분포 비교 — 분포가 다르면 그 차이를 점수로.
    if prev_pips != cur_pips:
        denom = max(len(prev_pips), len(cur_pips), 1)
        diff = _multiset_diff_count(prev_pips, cur_pips)
        return min(1.0, diff / denom)

    # 2) pip 분포 동일 — 자리가 바뀐 주사위를 센다.
    #
    #    track_id로 짝을 짓지 않는다. 굴림통에 넣었다 쏟은 주사위는 화면에서
    #    사라졌다 나타나므로 ByteTrack이 새 track_id를 준다. 그 track_id를
    #    "신뢰 불가"로 빼면, 4개를 킵하고 1개만 다시 굴려 같은 눈이 나왔을 때
    #    남는 4개가 전부 제자리라 점수가 0이 되고 굴림이 통째로 사라진다.
    #
    #    대신 좌표로 1:1 짝을 짓는다. 가렸다 치우기는 모든 주사위가 제자리라
    #    짝이 다 맞아 0점이고, 재굴림된 주사위만 짝지을 빈 자리가 없어 이동으로
    #    남는다. track_id 재할당에 영향받지 않는 것이 이 방식의 핵심이다.
    prev_centers = [center for center, _ in snapshot.items.values()]
    taken = [False] * len(prev_centers)
    moved = 0
    for d in current:
        # 짝으로 인정할 최대 거리. 주사위가 그만큼도 안 움직였으면 제자리다.
        limit = min(d.bbox.w, d.bbox.h) * center_shift_ratio
        best: int | None = None
        best_dist = limit
        for i, prev_center in enumerate(prev_centers):
            if taken[i]:
                continue
            dx = d.center[0] - prev_center[0]
            dy = d.center[1] - prev_center[1]
            dist = (dx * dx + dy * dy) ** 0.5
            if dist <= best_dist:
                best, best_dist = i, dist
        if best is None:
            moved += 1
        else:
            taken[best] = True
    return moved / len(current)


def _multiset_diff_count(a: list[int], b: list[int]) -> int:
    """두 정렬 multiset 사이에서 한쪽에만 있는 원소 개수 (대칭차의 크기).

    예: [1,1,2,3] vs [1,2,2,3] → 1 (1 하나 빠지고 2 하나 늘어 = 변화 1개).
    """
    ca, cb = Counter(a), Counter(b)
    diff = 0
    for v in set(ca) | set(cb):
        diff += abs(ca[v] - cb[v])
    # 한 쪽에서 빠지고 다른 쪽에서 들어온 건 같은 "변화 1건"이므로 절반.
    return diff // 2 + diff % 2


def _mode(buf: deque[str | None]) -> str | None:
    """버퍼 내 None이 아닌 값들의 최빈값. 비어있거나 모두 None이면 None."""
    counts = Counter(pid for pid in buf if pid is not None)
    if not counts:
        return None
    return counts.most_common(1)[0][0]


# ── 미사용 export 호환 (기존 import 깨지지 않도록) ────────────────────────────
__all__ = ["BBox", "HandDet", "RollAttributor", "RollState"]
