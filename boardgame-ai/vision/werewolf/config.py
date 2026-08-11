"""WerewolfVisionPipeline 설정."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class WerewolfVisionConfig:
    """WerewolfVisionPipeline 하드웨어·IO 설정."""

    # 카메라 / 소스
    source: int | str = 0
    resolution: tuple[int, int] = (1920, 1080)
    target_fps: int = 30
    frame_skip: int = 0

    # MediaPipe Hand
    # 카드 인식은 인식률 문제로 제거됐다. 이 파이프라인은 손만 본다.
    mp_max_num_hands: int = 8
    mp_min_detection_confidence: float = 0.5
    mp_min_tracking_confidence: float = 0.5

    # 시작 시 워밍업 프레임 (이 기간은 GameEvent 송신 skip)
    warmup_frames: int = 60

    # 디버그·로깅
    debug_overlay: bool = False
    jsonl_log_path: Path | None = None

    def __post_init__(self) -> None:
        if self.jsonl_log_path is not None:
            self.jsonl_log_path = Path(self.jsonl_log_path)
