"""주사위 눈 수 카운터 (OpenCV HoughCircles / SimpleBlobDetector).

개선사항:
- CLAHE로 대비 정규화 (조명 변화 대응)
- 크롭 시 패딩 추가 (bbox 경계 노이즈 제거)
- 흰/어두운 주사위 모두 대응 (INV/NORMAL 둘 다 시도)
- 파라미터를 외부에서 주입 가능 (튜닝 도구 연동)

bbox 는 정규화 BBox (0.0~1.0). frame_bgr 은 원본 BGR 이미지.
반환: 1~6 정수 또는 None (인식 실패).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from vision.schemas import BBox

# 크롭 패딩 (bbox 짧은 변 대비 비율)
_CROP_PAD_RATIO = 0.05


@dataclass
class DotCounterParams:
    """튜닝 도구에서 조정 가능한 파라미터.

    기본값은 실제 시연 조명(6500K, 밝기 100, 전구 2개)에서 tools/tune_dot_counter.py
    로 맞춘 값이다. 주사위 5개가 전부 확정되고 원본 일치율이 90% 안팎으로 유지되는
    지점이다. 조명을 바꾸면 이 값도 다시 맞춰야 한다.
    """

    dp: float = 0.6
    min_dist_ratio: float = 0.06
    # 이전 110. 경계 문턱을 올려 주사위 표면의 미세한 얼룩이 원으로 잡히지 않게 한다.
    canny_upper: int = 120
    # 이전 8. 누산 문턱을 두 배로 올린 것이 깜빡임을 잡은 결정적 변경이다 —
    # 낮으면 눈이 아닌 곳에서도 원이 성립해 프레임마다 다른 개수가 나온다.
    accum_thresh: int = 16
    radius_min_ratio: float = 0.05
    radius_max_ratio: float = 0.09
    # CLAHE. 이전 2.1. 대비를 과하게 끌어올리면 밝은 조명에서 표면 노이즈까지
    # 함께 살아나 원 후보가 늘어난다.
    clahe_clip: float = 1.5
    clahe_grid: int = 4
    # Blob
    blob_min_area_ratio: float = 0.003
    blob_max_area_ratio: float = 0.06
    blob_min_circularity: float = 0.45
    blob_min_convexity: float = 0.65
    blob_min_inertia: float = 0.35


def _crop_dice(frame_bgr: Any, bbox: BBox, pad_ratio: float = _CROP_PAD_RATIO) -> Any | None:
    """BBox 정규화 좌표로 주사위 크롭 (패딩 포함)."""
    h, w = frame_bgr.shape[:2]
    bw = (bbox.x2 - bbox.x1) * w
    bh = (bbox.y2 - bbox.y1) * h
    pad_x = int(bw * pad_ratio)
    pad_y = int(bh * pad_ratio)
    x1 = max(0, int(bbox.x1 * w) - pad_x)
    y1 = max(0, int(bbox.y1 * h) - pad_y)
    x2 = min(w, int(bbox.x2 * w) + pad_x)
    y2 = min(h, int(bbox.y2 * h) + pad_y)
    if x2 <= x1 or y2 <= y1:
        return None
    return frame_bgr[y1:y2, x1:x2]


def _preprocess(crop_bgr: Any, p: DotCounterParams) -> Any:
    """CLAHE 대비 정규화 + 가우시안 블러."""
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(
        clipLimit=p.clahe_clip,
        tileGridSize=(p.clahe_grid, p.clahe_grid),
    )
    gray = clahe.apply(gray)
    return gray


def _count_with_hough(gray: Any, short_side: int, p: DotCounterParams) -> int | None:
    """HoughCircles로 원 개수. 흰/어두운 주사위 둘 다 시도."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    min_r = max(2, int(short_side * p.radius_min_ratio))
    max_r = max(min_r + 2, int(short_side * p.radius_max_ratio))
    min_dist = max(1, int(short_side * p.min_dist_ratio))

    circles = cv2.HoughCircles(
        blurred,
        cv2.HOUGH_GRADIENT,
        dp=p.dp,
        minDist=min_dist,
        param1=p.canny_upper,
        param2=p.accum_thresh,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles is not None:
        count = circles.shape[1]
        if 1 <= count <= 6:
            return count

    # 반전 이미지로 재시도 (어두운 배경 + 밝은 pip)
    inv = cv2.bitwise_not(blurred)
    circles2 = cv2.HoughCircles(
        inv,
        cv2.HOUGH_GRADIENT,
        dp=p.dp,
        minDist=min_dist,
        param1=p.canny_upper,
        param2=p.accum_thresh,
        minRadius=min_r,
        maxRadius=max_r,
    )
    if circles2 is not None:
        count = circles2.shape[1]
        if 1 <= count <= 6:
            return count

    return None


def _count_with_blob(gray: Any, p: DotCounterParams) -> int | None:
    """SimpleBlobDetector fallback. 흰/어두운 주사위 둘 다 시도."""
    area = gray.shape[0] * gray.shape[1]
    bp = cv2.SimpleBlobDetector_Params()
    bp.filterByArea = True
    bp.minArea = max(4.0, area * p.blob_min_area_ratio)
    bp.maxArea = area * p.blob_max_area_ratio
    bp.filterByCircularity = True
    bp.minCircularity = p.blob_min_circularity
    bp.filterByConvexity = True
    bp.minConvexity = p.blob_min_convexity
    bp.filterByInertia = True
    bp.minInertiaRatio = p.blob_min_inertia

    detector = cv2.SimpleBlobDetector_create(bp)

    # 어두운 pip (흰 주사위)
    thresh_inv = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        blockSize=11,
        C=4,
    )
    kp = detector.detect(thresh_inv)
    if 1 <= len(kp) <= 6:
        return len(kp)

    # 밝은 pip (어두운 주사위)
    thresh = cv2.adaptiveThreshold(
        gray,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        blockSize=11,
        C=4,
    )
    kp2 = detector.detect(thresh)
    if 1 <= len(kp2) <= 6:
        return len(kp2)

    return None


class DotCounter:
    """주사위 눈 수 인식기.

    params 를 외부에서 주입하면 튜닝 도구와 연동 가능.
    """

    def __init__(self, params: DotCounterParams | None = None) -> None:
        self.params = params or DotCounterParams()

    def count(self, frame_bgr: Any, bbox: BBox) -> int | None:
        crop = _crop_dice(frame_bgr, bbox)
        if crop is None or crop.size == 0:
            return None

        gray = _preprocess(crop, self.params)
        short_side = min(gray.shape[0], gray.shape[1])

        if short_side < 10:
            return None

        result = _count_with_hough(gray, short_side, self.params)
        if result is not None:
            return result

        return _count_with_blob(gray, self.params)

    def count_with_debug(self, frame_bgr: Any, bbox: BBox) -> tuple[int | None, Any]:
        """튜닝 도구용: (결과, 시각화 이미지) 반환."""
        crop = _crop_dice(frame_bgr, bbox)
        if crop is None or crop.size == 0:
            return None, np.zeros((100, 100, 3), dtype=np.uint8)

        gray = _preprocess(crop, self.params)
        short_side = min(gray.shape[0], gray.shape[1])
        vis = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)

        result = _count_with_hough(gray, short_side, self.params)

        # 감지된 원 시각화
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        min_r = max(2, int(short_side * self.params.radius_min_ratio))
        max_r = max(min_r + 2, int(short_side * self.params.radius_max_ratio))
        min_dist = max(1, int(short_side * self.params.min_dist_ratio))
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=self.params.dp,
            minDist=min_dist,
            param1=self.params.canny_upper,
            param2=self.params.accum_thresh,
            minRadius=min_r,
            maxRadius=max_r,
        )
        if circles is not None:
            for x, y, r in circles[0]:
                cv2.circle(vis, (int(x), int(y)), int(r), (0, 255, 0), 1)
                cv2.circle(vis, (int(x), int(y)), 2, (0, 0, 255), -1)

        label = str(result) if result is not None else "?"
        cv2.putText(
            vis, label, (4, vis.shape[0] - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 200, 255), 2
        )

        if result is None:
            result = _count_with_blob(gray, self.params)

        return result, vis
