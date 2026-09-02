"""요트 다이스 비전 파이프라인.

CameraManager가 공급하는 frame_queue에서 프레임을 소비해 처리한다.
"""

from __future__ import annotations

import queue
import time
from typing import Any

import cv2

from bridge.interface import Bridge
from core.constants import DEFAULT_PARAMS
from core.events import FusionContext
from core.models import Player
from vision.attribution.roll_attributor import RollAttributor
from vision.attribution.seat_matcher import (
    MARGIN_THRESHOLD,
    match_player_by_arm,
    players_with_both_hands_tracked,
)
from vision.yacht.config import VisionConfig
from vision.debug.jsonl_logger import JsonlLogger
from vision.debug.overlay import draw_overlay
from vision.detectors.dot_counter import DotCounter
from vision.detectors.gesture_classifier import GestureClassifier
from vision.detectors.hand_detector import HandDetector
from vision.detectors.yolo_detector import YoloDetector
from vision.fusion.engine import FusionEngine

# Benchmark hook (BENCH_TRACE=0이면 bench_log()는 NullHandler만 달린 no-op).
# 매 프레임 import 비용 방지를 위해 모듈 상단에서 한 번만 import.
try:
    from benchmarks.common.trace_setup import bench_log as _bench_log, is_bench as _is_bench
except Exception:
    _bench_log = None
    _is_bench = None
from vision.geometry.arm_vector import compute_arm_angle
from vision.schemas import BBox, HandDet, YoloDet
from vision.yacht.schemas import YachtFramePerception
from vision.tracking.byte_tracker import ByteTracker
from vision.tracking.dice_manager import DiceManager
from vision.tracking.hand_tracker import MAX_MATCH_ATTEMPTS, HandTracker


class VisionPipeline:
    def __init__(
        self,
        config: VisionConfig,
        bridge: Bridge,
        players: list[Player],
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._players = players
        self._running = False
        self._active = False  # 요트 게임 시작 시 True로 전환
        self._frame_id = 0

        self._yolo = YoloDetector(
            weights_path=config.weights_path,
            conf=config.yolo_conf,
            iou=config.yolo_iou,
            imgsz=config.yolo_imgsz,
        )
        self._hand_detector = HandDetector(
            max_num_hands=config.mp_max_num_hands,
            min_detection_confidence=config.mp_min_detection_confidence,
            min_tracking_confidence=config.mp_min_tracking_confidence,
        )
        self._gesture_clf = GestureClassifier()
        self._hand_tracker = HandTracker()
        self._prev_gestures: dict[int, str | None] = {}
        # min_hits=1: 검출된 주사위를 1프레임 만에 확정해 트랙으로 반환한다.
        # 기본값 2는 "연속 2프레임 매칭"을 요구하는데, YOLO가 일부 주사위를
        # 프레임마다 들쭉날쭉 잡으면 hit_streak가 계속 0으로 리셋돼 그 주사위가
        # 영영 확정되지 않는다(로그에 5개 중 3~4개만 찍히고 굴림 미발화).
        # 굴림 finalize는 별도로 stable_frames>=15 + 변화점수 게이트가 막아주므로
        # 1프레임 확정으로 낮춰도 단발 오검출이 가짜 굴림을 일으키지는 않는다.
        self._byte_tracker = ByteTracker(min_hits=1)
        self._dot_counter = DotCounter()
        self._dice_manager = DiceManager(
            motion_threshold=float(DEFAULT_PARAMS["motion_threshold_norm"]),
            stabilization_frames=10,
            history_window=config.dice_history_window,
            pip_buffer_size=config.dice_count_buffer,
        )
        self._roll_attributor = RollAttributor(
            stabilization_frames=15,
            grab_fallback_window_frames=config.grab_fallback_window_frames,
            roll_lift_threshold=config.roll_lift_threshold,
            motion_threshold=float(DEFAULT_PARAMS["motion_threshold_norm"]),
        )
        self._fusion = FusionEngine(yacht_escape_padding=config.tray_escape_padding)
        self._jsonl_logger = JsonlLogger(config.jsonl_log_path)

        self._last_event_data: dict | None = None
        self._event_banner_ttl: int = 0
        self._fsm_state_version: int = 0
        self._has_context: bool = False
        # FSM이 알려준 현재 턴 플레이어. RollAttributor에 전달해 다른 플레이어가
        # 트레이 근처에서 손을 움직이거나 dice를 만져도 점유/actor 판정에 영향 X.
        self._active_player: str | None = None

        self._bridge.on_fusion_context(self._on_fusion_context, game_type="yacht")

    def start(self, frame_queue: "queue.Queue[Any]") -> None:
        """CameraManager가 공급하는 frame_queue에서 프레임을 소비해 처리 (블로킹)."""
        self._running = True
        skip_counter = 0
        print("[yacht_pipeline] 시작")

        try:
            while self._running:
                try:
                    frame = frame_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if not self._active:
                    continue  # 비활성 상태: 큐 소진만, ML 처리 스킵

                if self._config.frame_skip > 0:
                    skip_counter += 1
                    if skip_counter <= self._config.frame_skip:
                        continue
                    skip_counter = 0

                ts = time.time()
                # Benchmark hook: FPS 계산용 (BENCH_TRACE=1에서만 실제 기록).
                if _is_bench is not None and _is_bench():
                    try:
                        _bench_log().info("pipeline_enter %d %.6f", self._frame_id, ts)
                    except Exception:
                        pass
                self._process_one(frame, self._frame_id, ts)
                self._frame_id += 1

                if self._config.debug_overlay and cv2.waitKey(1) & 0xFF == ord("q"):
                    break
        finally:
            if self._config.debug_overlay:
                cv2.destroyAllWindows()
            try:
                self._hand_detector.close()
            finally:
                self._jsonl_logger.close()

    def stop(self) -> None:
        self._running = False

    def set_active(self, enabled: bool) -> None:
        self._active = enabled

    def update_players(self, players: list[Player]) -> None:
        self._players = players

    def _process_one(self, frame_bgr: Any, frame_id: int, ts: float) -> None:
        h, w = frame_bgr.shape[:2]

        yolo_dets = self._yolo.detect(frame_bgr)
        tray, tray_inner, roll_tray, dice_dets = _split_dets(yolo_dets)

        if tray is not None and self._config.tray_mask_padding > 0:
            dice_dets = _filter_dice_inside_tray(
                dice_dets, tray, padding=self._config.tray_mask_padding
            )

        tracked = self._byte_tracker.update(dice_dets, frame_id)
        dice_states = self._dice_manager.update(tracked, frame_bgr, self._dot_counter)
        dice_states.sort(key=lambda d: d.track_id)

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        raw_hands = self._hand_detector.detect(frame_rgb)
        hands = self._stabilize_hands(raw_hands)

        perception = YachtFramePerception(
            frame_id=frame_id,
            ts=ts,
            image_hw=(h, w),
            tray=tray,
            tray_inner=tray_inner,
            roll_tray=roll_tray,
            dice=dice_states,
            hands=hands,
        )

        roll_actor = self._roll_attributor.update(perception, active_player=self._active_player)
        if roll_actor is not None:
            perception.roll_actor_id = roll_actor
        if self._roll_attributor.just_finalized:
            perception.roll_just_confirmed = True
        perception.phase_hints = {
            "dice_all_stable": perception.dice_all_stable(
                int(DEFAULT_PARAMS["stabilization_frames"])
            ),
            "dice_count": len(dice_states),
            "roll_state": self._roll_attributor.state.name,
        }

        if frame_id % 30 == 0 and self._has_context:
            hand_info = [(h.handedness, h.player_id, h.gesture) for h in hands]
            dice_info = [(d.track_id, d.pip_count, d.stable_frames) for d in dice_states]
            # roll_tray와 굴림 상태를 함께 찍는다.
            #
            # 굴림이 발화하지 않을 때 어느 게이트에 걸렸는지 이 줄만 보고 알 수
            # 있어야 한다. 예전에는 tray/dice/hands만 찍어서, 굴림통이 안 잡힌
            # 건지 손이 안 잡힌 건지 상태가 안 넘어간 건지 구분할 수 없었다.
            print(
                f"[yacht f{frame_id}] "
                f"tray={'O' if tray else 'X'} "
                f"cup={'O' if roll_tray else 'X'}  "
                f"roll={self._roll_attributor.state.name}  "
                f"dice={dice_info}  "
                f"hands={hand_info}"
            )

        events = self._fusion.feed(perception)
        if frame_id >= self._config.warmup_frames:
            for event in events:
                self._bridge.send_game_event(event, self._fsm_state_version)
                if event.event_type == "ROLL_CONFIRMED":
                    self._last_event_data = event.data if isinstance(event.data, dict) else None
                    self._event_banner_ttl = 90

        self._jsonl_logger.log(perception)

        if self._config.debug_overlay:
            warmup_remaining = max(0, self._config.warmup_frames - frame_id)
            vis = draw_overlay(
                frame_bgr.copy(),
                perception,
                recent_event=self._last_event_data,
                event_ttl_frames=self._event_banner_ttl,
                warmup_remaining=warmup_remaining,
            )
            if self._event_banner_ttl > 0:
                self._event_banner_ttl -= 1
            cv2.imshow("VisionPipeline", vis)

    def _on_fusion_context(self, ctx: FusionContext, state_version: int) -> None:
        self._has_context = True
        self._fusion.update_context(ctx)
        self._fsm_state_version = state_version
        self._active_player = ctx.active_player

    def _stabilize_hands(self, raw_hands: list[HandDet]) -> list[HandDet]:
        detections: list[tuple[tuple[float, float], float]] = []
        for h in raw_hands:
            angle = compute_arm_angle(h.landmarks_21)
            detections.append((h.wrist_xy, angle))

        tracks = self._hand_tracker.update(detections)
        active = self._hand_tracker.active_tracks()

        stabilized: list[HandDet] = []
        for raw, track in zip(raw_hands, tracks, strict=True):
            track.handedness_buf.append(raw.handedness)
            confirmed_hd = track.confirmed_handedness
            stable_handedness = confirmed_hd or raw.handedness

            # handedness 다수결이 안정화된 후 바뀌었다면 player_id 재매칭 트리거.
            # MediaPipe 초기 오인식으로 잘못된 우/좌가 잡혀 player_id가 굳었을 때
            # 자정할 수 있도록 한다.
            if (
                confirmed_hd is not None
                and track.last_match_handedness is not None
                and confirmed_hd != track.last_match_handedness
            ):
                track.pending_match = True
                track.match_attempts = 0

            # 매칭 시도: pending이거나, confirmed handedness가 안정됐는데 아직
            # 한 번도 매칭 안 한 트랙. seat_zone 등록자 있는 경우만.
            should_match = (
                self._players
                and track.frames_since_entry >= 3
                and confirmed_hd is not None
                and (track.pending_match or track.last_match_handedness != confirmed_hd)
            )
            if should_match:
                # 같은 player_id의 양손이 모두 다른 트랙에 잡혀 있으면 후보 제외.
                # 단, 자기 자신이 그 player_id로 confirm된 적이 있다면 자기를 빼서
                # 제외 집합에서 self-exclusion이 일어나지 않게 한다.
                self_pid = track.confirmed_player_id
                excluded = players_with_both_hands_tracked(
                    [t for t in active if t.track_id != track.track_id]
                )
                if self_pid is not None:
                    excluded.discard(self_pid)

                pid, _score, margin = match_player_by_arm(
                    handedness=confirmed_hd,
                    entry_wrist_xy=track.entry_wrist_xy,
                    entry_arm_angle=track.entry_arm_angle,
                    players=self._players,
                    excluded_player_ids=excluded,
                )
                track.player_id_buf.append(pid)
                track.match_attempts += 1
                track.last_match_handedness = confirmed_hd
                # margin 충분 → 확정. 부족하면 Hold, MAX_MATCH_ATTEMPTS 타임아웃 시 강제 확정.
                if margin >= MARGIN_THRESHOLD or track.match_attempts >= MAX_MATCH_ATTEMPTS:
                    track.pending_match = False

            # 확정값 우선, 미확정이면 best-effort 최빈값으로 폴백.
            # 등록된 손은 항상 누군가로 매칭되어야 actor 산정이 None으로 새지 않고
            # 차례 위반(옆사람 굴림)이 감지된다.
            player_id = track.confirmed_player_id or track.best_effort_player_id
            prev_gesture = self._prev_gestures.get(track.track_id)
            stable_hand = HandDet(
                handedness=stable_handedness,
                wrist_xy=raw.wrist_xy,
                landmarks_21=raw.landmarks_21,
            )
            gesture = self._gesture_clf.classify_with_prev(stable_hand, prev_gesture)
            self._prev_gestures[track.track_id] = gesture

            stabilized.append(
                HandDet(
                    handedness=stable_handedness,
                    wrist_xy=raw.wrist_xy,
                    landmarks_21=raw.landmarks_21,
                    gesture=gesture,
                    player_id=player_id,
                    arm_angle=track.arm_angle,
                )
            )

        live_ids = {t.track_id for t in self._hand_tracker.active_tracks()}
        stale = [tid for tid in self._prev_gestures if tid not in live_ids]
        for tid in stale:
            del self._prev_gestures[tid]

        return stabilized


def _split_dets(
    dets: list[YoloDet],
) -> tuple[BBox | None, BBox | None, BBox | None, list[YoloDet]]:
    tray = tray_inner = roll_tray = None
    dice_dets: list[YoloDet] = []
    for d in dets:
        if d.cls_name == "tray":
            tray = d.bbox
        elif d.cls_name == "tray_inner":
            tray_inner = d.bbox
        elif d.cls_name == "roll_tray":
            roll_tray = d.bbox
        elif d.cls_name == "dice":
            dice_dets.append(d)
    return tray, tray_inner, roll_tray, dice_dets


def _filter_dice_inside_tray(dice_dets: list[YoloDet], tray: BBox, padding: float) -> list[YoloDet]:
    pad_x = tray.w * padding
    pad_y = tray.h * padding
    x1, y1 = tray.x1 - pad_x, tray.y1 - pad_y
    x2, y2 = tray.x2 + pad_x, tray.y2 + pad_y
    return [d for d in dice_dets if x1 <= d.bbox.cx <= x2 and y1 <= d.bbox.cy <= y2]
