"""한밤의 늑대인간 전용 비전 파이프라인.

VisionPipeline(요트) 과 독립적으로 동작. 공통 컴포넌트(HandDetector,
GestureClassifier, HandTracker, FusionEngine)는 재사용하고,
요트 전용 컴포넌트(DiceManager, DotCounter, RollAttributor)는 포함하지 않는다.

카드 인식은 인식률이 낮아 제거했다. 이제 손만 본다 — 야간 진행은 OK 사인,
투표는 좌석 포인팅으로 처리하며 둘 다 카드 감지를 필요로 하지 않는다.
덕분에 프레임당 YOLO 추론이 사라졌다.

처리 흐름:
  CameraManager (frame_queue)
    → HandDetector + GestureClassifier + HandTracker
    → FramePerception 조립 (hands 필드만 채움)
    → FusionEngine (WerewolfRules 주입됨)
    → Bridge.send_game_event()
"""

from __future__ import annotations

import queue
import time
from typing import Any

import cv2

from bridge.interface import Bridge
from core.events import FusionContext
from core.models import Player
from vision.attribution.seat_matcher import (
    MARGIN_THRESHOLD,
    match_player_by_arm,
    players_with_both_hands_tracked,
)
from vision.debug.jsonl_logger import JsonlLogger
from vision.detectors.gesture_classifier import GestureClassifier
from vision.detectors.hand_detector import HandDetector
from vision.fusion.engine import FusionEngine
from vision.fusion.werewolf_rules import WerewolfRules
from vision.geometry.arm_vector import compute_arm_angle
from vision.schemas import FramePerception, HandDet
from vision.tracking.hand_tracker import MAX_MATCH_ATTEMPTS, HandTracker
from vision.werewolf.config import WerewolfVisionConfig


class WerewolfVisionPipeline:
    """한밤의 늑대인간 비전 파이프라인.

    VisionPipeline(요트 전용) 과 완전히 독립된 클래스.
    공통 컴포넌트만 재사용하고 요트 전용 로직은 포함하지 않는다.
    """

    def __init__(
        self,
        config: WerewolfVisionConfig,
        bridge: Bridge,
        players: list[Player],
    ) -> None:
        self._config = config
        self._bridge = bridge
        self._players = players
        self._running = False
        self._active = False  # start_werewolf_game() 호출 시 True로 전환
        self._frame_id = 0
        self._last_log_ts: float = 0.0

        # 손 파이프라인 (기존 컴포넌트 재사용)
        self._hand_detector = HandDetector(
            max_num_hands=config.mp_max_num_hands,
            min_detection_confidence=config.mp_min_detection_confidence,
            min_tracking_confidence=config.mp_min_tracking_confidence,
        )
        self._gesture_clf = GestureClassifier()
        self._hand_tracker = HandTracker()
        # track_id → 직전 제스처 (release 감지용)
        self._prev_gestures: dict[int, str | None] = {}

        # Fusion (WerewolfRules 주입)
        self._fusion = FusionEngine()
        self._werewolf_rules = WerewolfRules()
        self._fusion.register_werewolf_rules(self._werewolf_rules)

        # 상태
        self._fsm_state_version: int = 0
        self._has_context: bool = False
        self._jsonl_logger = JsonlLogger(config.jsonl_log_path)

        # FSM → FusionContext 수신 핸들러 등록
        self._bridge.on_fusion_context(self._on_fusion_context, game_type="werewolf")

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    def start(self, frame_queue: "queue.Queue[Any]") -> None:
        """CameraManager가 공급하는 frame_queue에서 프레임을 소비해 처리 (블로킹)."""
        self._running = True
        skip_counter = 0
        print("[werewolf_pipeline] 시작  hands-only (카드 인식 없음)")

        try:
            while self._running:
                try:
                    frame = frame_queue.get(timeout=1.0)
                except queue.Empty:
                    continue

                if not self._active:
                    continue  # 비활성 상태: 카메라 버퍼 소진만, ML 처리 스킵

                if self._config.frame_skip > 0:
                    skip_counter += 1
                    if skip_counter <= self._config.frame_skip:
                        continue
                    skip_counter = 0

                ts = time.time()
                self._process_one(frame, self._frame_id, ts)
                self._frame_id += 1
        finally:
            try:
                self._hand_detector.close()
            finally:
                self._jsonl_logger.close()

    def stop(self) -> None:
        self._running = False

    def set_active(self, enabled: bool) -> None:
        self._active = enabled

    def update_players(self, players: list[Player]) -> None:
        """백엔드에서 플레이어 목록이 갱신될 때 호출."""
        self._players = players

    # ── 내부 처리 ──────────────────────────────────────────────────────────────

    def _process_one(self, frame_bgr: Any, frame_id: int, ts: float) -> None:
        h, w = frame_bgr.shape[:2]

        # 1) 손 감지 (RGB 변환 후 MediaPipe)
        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        raw_hands = self._hand_detector.detect(frame_rgb)

        # 2) 손 시간적 안정화 + player_id 배정
        hands = self._stabilize_hands(raw_hands)

        # 3) FramePerception 조립
        #    dice/tray 필드는 기본값(None/[]) 그대로 — 요트 전용 필드
        perception = FramePerception(
            frame_id=frame_id,
            ts=ts,
            image_hw=(h, w),
            hands=hands,
        )

        if self._has_context and ts - self._last_log_ts >= 1.0:
            self._last_log_ts = ts
            hand_info = [(h.handedness, h.player_id, h.gesture) for h in hands]
            print(f"[werewolf f{frame_id}] hands={hand_info}")

        # 4) FusionEngine → GameEvent 생성
        events = self._fusion.feed(perception)
        if frame_id >= self._config.warmup_frames:
            for event in events:
                self._bridge.send_game_event(event, self._fsm_state_version)

        # 5) JSONL 로깅
        self._jsonl_logger.log(perception)

    def _on_fusion_context(self, ctx: FusionContext, state_version: int) -> None:
        self._has_context = True
        self._fusion.update_context(ctx)
        self._fsm_state_version = state_version

    # ── 손 안정화 ──────────────────────────────────────────────────────────────

    def _stabilize_hands(self, raw_hands: list[HandDet]) -> list[HandDet]:
        """HandTracker 로 frame-to-frame track 을 유지하고 player_id 를 안정화한다."""
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

            # handedness 다수결이 뒤집히면 player_id 재매칭 트리거.
            if (
                confirmed_hd is not None
                and track.last_match_handedness is not None
                and confirmed_hd != track.last_match_handedness
            ):
                track.pending_match = True
                track.match_attempts = 0

            should_match = (
                self._players
                and track.frames_since_entry >= 3
                and confirmed_hd is not None
                and (track.pending_match or track.last_match_handedness != confirmed_hd)
            )
            if should_match:
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
                if margin >= MARGIN_THRESHOLD or track.match_attempts >= MAX_MATCH_ATTEMPTS:
                    track.pending_match = False

            # confirmed_player_id는 "2표+마진" 게이트로 초기 오매칭 굳음을 막지만,
            # 투표 포인팅·OK 사인처럼 짧게 손을 뻗는 동작은 표를 못 모아 None이 되기 쉽다.
            # None이면 best_effort(마진 없이 최빈 non-None)로 폴백해 "등록된 손은
            # 항상 가장 비슷한 플레이어로 매칭"을 보장한다. 둘 다 None이면(=아직 한 번도
            # 매칭된 적 없음) None 유지.
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
