"""요트 다이스 비전 파이프라인 설정."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class VisionConfig:
    # 카메라 / 소스 (CameraManager가 관리하므로 파이프라인에서 직접 사용하지 않음)
    source: int | str = 0
    resolution: tuple[int, int] = (1920, 1080)
    target_fps: int = 30
    frame_skip: int = 0

    # YOLO
    weights_path: str | Path = "weights/yacht_v4.pt"
    yolo_conf: float = 0.35
    yolo_iou: float = 0.5
    yolo_imgsz: int = 640
    # 주사위를 어디서 찾는가.
    #   "hybrid" — 트레이 안의 흰 덩어리(DiceFinder)를 기본으로 하고 YOLO dice를
    #              보조 증거로 쓴다. 기본.
    #                · 덩어리 + 흰색          → 주사위 (YOLO가 놓쳐도 잡는다: 킵존)
    #                · 덩어리 + YOLO가 가리킴 → 색이 틀어져도 주사위
    #                · 트레이 영역을 못 찾음   → YOLO 검출만으로 이어 간다
    #              눈은 어느 경우든 그 박스에서 DotCounter(face)가 센다.
    #   "finder" — 흰 덩어리만. YOLO dice는 안 본다.
    #   "yolo"   — YOLO dice 클래스만. 지금 트레이(빨간 펠트)에서는 프레임마다
    #              한두 개씩 빠졌다 잡혔다 하고(정지 카운터가 0으로 돌아가 굴림이
    #              unstable로 끝난다) 킵존 주사위를 못 잡는다 (2026-11-11 실물
    #              14장: 70개 중 YOLO 59, 킵존 0 / hybrid 69).
    # YOLO는 어느 쪽이든 트레이·굴림통을 찾는 데 쓴다.
    dice_source: str = "hybrid"

    # MediaPipe Hand
    mp_max_num_hands: int = 8
    mp_min_detection_confidence: float = 0.5
    mp_min_tracking_confidence: float = 0.5
    mp_model_complexity: int = 0

    # RollAttributor
    roll_lift_threshold: float = 0.02
    grab_fallback_window_frames: int = 60

    # DiceManager
    dice_count_buffer: int = 11
    dice_history_window: int = 10

    warmup_frames: int = 60
    tray_mask_padding: float = 0.1
    # DICE_ESCAPED 판정용 tray bbox 외측 패딩 (tray 짧은 변 대비 비율).
    # tray 경계에 살짝 걸친 dice(킵존 가장자리 등)를 escape로 오인하지 않도록
    # tray 외부로 이 비율 이상 나가야 실제 이탈로 본다.
    tray_escape_padding: float = 0.15

    debug_overlay: bool = False
    jsonl_log_path: Path | None = None

    def __post_init__(self) -> None:
        self.weights_path = Path(self.weights_path)
        if self.jsonl_log_path is not None:
            self.jsonl_log_path = Path(self.jsonl_log_path)
