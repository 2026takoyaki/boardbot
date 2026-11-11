"""주사위 눈 수 카운터.

기본은 **면 찾기(face)** 방식이다 — 흰 면을 직접 찾고 그 안의 구멍을 센다.

    1. bbox를 넉넉히 넓혀 자른다 — YOLO 박스가 밀려도 면 전체가 들어온다
    2. 세 채널 최솟값을 Otsu로 갈라 밝은 덩어리(흰 면)를 찾는다. 빨간 펠트와
       검은 트레이는 최솟값이 낮아 면이 아니다
    3. bbox 중심에 가장 가까운 면 하나를 고른다 (이웃 주사위와 붙으면 bbox로 자른다)
    4. 면 안의 구멍 = 눈. 면 바깥은 아예 보지 않으니 테두리·그림자·펠트가
       끼어들 자리가 없다
    5. 면 가장자리에 걸려 면 윤곽을 파고든 눈은 볼록 껍질로 되살린다 — 단
       둥글고 다른 눈과 크기가 비슷할 때만

박스를 안쪽으로 깎아 그 안을 세던 방식(components)은 박스 위치에 극도로
민감했다. 실물 화면(2026-11-11)에서 박스를 15% 밀자 5개 중 0~1개만 맞혔고,
면 찾기는 밀어도 결과가 그대로였다.

예전 방식(HoughCircles → SimpleBlobDetector)은 method="hough"로 남겨 둔다.
원 검출은 1~6개 중 **아무 개수나 나오면 그대로 채택**해서 틀린 값이 그대로
통과했고, 크롭에 패딩을 더해 테두리·그림자가 원 후보로 들어왔다.

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

    # ── 연결 성분 방식 (기본) ──
    method: str = "face"  # "face" | "components" | "hough"
    # 면 찾기: bbox를 이만큼 넓혀 자른다(변 길이 대비, 한쪽).
    face_expand: float = 0.25
    # 면 찾기: 작업 이미지 긴 변(px).
    face_work_size: int = 128
    # 면 찾기: 눈 넓이 범위(면 넓이 대비). 1눈은 크다.
    face_pip_min: float = 0.006
    face_pip_max: float = 0.15
    # bbox를 안쪽으로 깎는 비율(변 길이 대비, 한쪽). YOLO 박스는 옆면과 그림자를
    # 조금씩 물고 있어서, 깎지 않으면 테두리가 눈으로 잡힌다.
    inset_ratio: float = 0.08
    # 크롭을 이 크기(px) 정사각형으로 키워서 본다.
    work_size: int = 96
    # 눈 하나의 넓이 범위(작업 이미지 넓이 대비). 표준 주사위 눈은 지름이 변의
    # 15~22% → 넓이 약 2~4%. 1눈은 더 크다.
    pip_min_area_ratio: float = 0.006
    pip_max_area_ratio: float = 0.12
    # 원형도 4πA/P². 완전한 원이 1.0. 눈은 작아서 픽셀화로 0.6~0.9가 나온다.
    pip_min_circularity: float = 0.5
    # 면과 눈의 밝기 차가 이보다 작으면 판정하지 않는다(가려짐·흐림).
    min_contrast: int = 40


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


def _crop_inset(frame_bgr: Any, bbox: BBox, inset_ratio: float) -> Any | None:
    """bbox를 안쪽으로 깎아 자른다."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = bbox.x1 * w, bbox.y1 * h, bbox.x2 * w, bbox.y2 * h
    dx, dy = (x2 - x1) * inset_ratio, (y2 - y1) * inset_ratio
    ix1, iy1 = max(0, int(round(x1 + dx))), max(0, int(round(y1 + dy)))
    ix2, iy2 = min(w, int(round(x2 - dx))), min(h, int(round(y2 - dy)))
    if ix2 - ix1 < 6 or iy2 - iy1 < 6:
        return None
    return frame_bgr[iy1:iy2, ix1:ix2]


def _pip_mask(crop_bgr: Any, p: DotCounterParams) -> tuple[Any, Any] | None:
    """(작업 이미지, 눈 마스크). 대비가 모자라면 None."""
    size = p.work_size
    img = cv2.resize(crop_bgr, (size, size), interpolation=cv2.INTER_CUBIC)
    # 세 채널 최솟값: 흰 면은 셋 다 밝고, 검은 눈은 셋 다 어둡고, 빨간 눈은
    # G·B가 어둡다. 회색(가중 평균)으로는 빨간 눈이 면과 잘 안 갈린다.
    dark = img.min(axis=2)
    dark = cv2.GaussianBlur(dark, (3, 3), 0)

    # 대비 = 면(중앙값)과 가장 어두운 곳의 차. 어두운 쪽을 하위 몇 %로 잡으면
    # 눈이 1~2개일 때 눈 넓이가 그 비율에 못 미쳐 "대비 없음"으로 떨어진다.
    lo, mid = np.percentile(dark, (0.5, 50))
    if mid - lo < p.min_contrast:
        return None

    _t, mask = cv2.threshold(dark, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    # 면 위의 잔티를 지운다. 눈은 작업 크기에서 지름 10px 이상이라 살아남는다.
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return img, mask


def _pip_blobs(mask: Any, p: DotCounterParams) -> list[tuple[float, tuple[float, float], bool]]:
    """눈 후보 덩어리: [(넓이, 중심, 길쭉한가)]. 테두리에 닿은 것은 버린다."""
    size = mask.shape[0]
    total = float(size * size)
    n, _labels, stats, centroids = cv2.connectedComponentsWithStats(mask, connectivity=8)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    perim_by_label: dict[int, float] = {}
    for c in contours:
        x, y = c[0][0]
        perim_by_label[int(_labels[y, x])] = cv2.arcLength(c, True)

    blobs: list[tuple[float, tuple[float, float], bool]] = []
    for i in range(1, n):
        x, y, bw, bh, area = stats[i]
        ratio = area / total
        if ratio < p.pip_min_area_ratio or ratio > p.pip_max_area_ratio * 2.2:
            continue
        # 테두리에 닿은 덩어리 = 옆면·그림자·이웃 주사위. 눈은 면 안쪽에 있다.
        if x <= 0 or y <= 0 or x + bw >= size or y + bh >= size:
            continue
        perim = perim_by_label.get(i, 0.0)
        circ = 4 * np.pi * area / (perim * perim) if perim > 0 else 0.0
        elongated = max(bw, bh) > 1.6 * min(bw, bh)
        # 길쭉한 덩어리는 붙은 두 눈일 수 있어 원형도를 묻지 않는다(아래에서 넓이로 판단).
        if not elongated and circ < p.pip_min_circularity:
            continue
        blobs.append((float(area), (float(centroids[i][0]), float(centroids[i][1])), elongated))
    return blobs


def _count_with_components(crop_bgr: Any, p: DotCounterParams) -> int | None:
    made = _pip_mask(crop_bgr, p)
    if made is None:
        return None
    _img, mask = made
    blobs = _pip_blobs(mask, p)
    if not blobs:
        return None

    size = mask.shape[0]
    total = float(size * size)
    areas = sorted(a for a, _c, _e in blobs)

    if len(blobs) == 1:
        area, (cx, cy), elongated = blobs[0]
        # 1눈: 크고 둥글고 가운데 있다. 하나만 잡혔는데 가운데가 아니면 다른 눈을
        # 놓친 것이라 판정하지 않는다.
        near_center = abs(cx - size / 2) < size * 0.2 and abs(cy - size / 2) < size * 0.2
        if near_center and not elongated and area / total <= p.pip_max_area_ratio:
            return 1
        return None

    # 붙은 눈 분리: 둥근 덩어리들의 중간 넓이를 눈 하나로 보고, 그보다 확연히 큰
    # 길쭉한 덩어리는 두 개로 센다(6눈의 한 줄이 붙는 경우가 흔하다).
    round_areas = sorted(a for a, _c, e in blobs if not e) or areas
    unit = float(np.median(round_areas))
    count = 0
    for area, _c, elongated in blobs:
        if area > unit * 1.7 and elongated:
            count += min(3, int(round(area / unit)))
        elif area > unit * 2.6:
            # 둥근데 지나치게 크다 = 그림자·얼룩. 셈에서 뺀다.
            continue
        else:
            count += 1
    if 1 <= count <= 6:
        return count
    return None


def _shape(contour: Any, face_area: float) -> tuple[float, float, bool]:
    """(면 대비 넓이, 원형도, 길쭉한가)."""
    area = cv2.contourArea(contour)
    perim = cv2.arcLength(contour, True)
    circ = 4 * np.pi * area / (perim * perim) if perim > 0 else 0.0
    _x, _y, bw, bh = cv2.boundingRect(contour)
    elongated = max(bw, bh) > 1.6 * max(1, min(bw, bh))
    return area / face_area, circ, elongated


def _find_face(frame_bgr: Any, bbox: BBox, p: DotCounterParams):
    """(작업 이미지, 면 마스크, 면 외곽선) 또는 None."""
    h, w = frame_bgr.shape[:2]
    x1, y1, x2, y2 = bbox.x1 * w, bbox.y1 * h, bbox.x2 * w, bbox.y2 * h
    bw, bh = x2 - x1, y2 - y1
    if bw < 6 or bh < 6:
        return None
    ex, ey = bw * p.face_expand, bh * p.face_expand
    cx1, cy1 = max(0, int(x1 - ex)), max(0, int(y1 - ey))
    cx2, cy2 = min(w, int(x2 + ex)), min(h, int(y2 + ey))
    crop = frame_bgr[cy1:cy2, cx1:cx2]
    if crop.size == 0:
        return None
    scale = p.face_work_size / max(crop.shape[:2])
    img = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)

    dark = cv2.GaussianBlur(img.min(axis=2), (3, 3), 0)
    # 어두운 쪽은 하위 0.2%. 1눈 하나는 크롭 넓이의 1% 남짓이라, 1%로 잡으면
    # 눈이 그 비율에 겨우 걸쳐 대비가 없다고 떨어진다.
    lo, mid = np.percentile(dark, (0.2, 99))
    if mid - lo < p.min_contrast:
        return None
    _t, bright = cv2.threshold(dark, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))

    # 원래 bbox 영역(작업 좌표). 면이 이웃 주사위와 붙어 커지면 여기로 자른다.
    bx1, by1 = (x1 - cx1) * scale, (y1 - cy1) * scale
    bx2, by2 = (x2 - cx1) * scale, (y2 - cy1) * scale
    box_area = (bx2 - bx1) * (by2 - by1)
    centre = ((bx1 + bx2) / 2, (by1 + by2) / 2)

    def pick(mask: Any) -> Any | None:
        n, labels, stats, cents = cv2.connectedComponentsWithStats(mask, connectivity=8)
        best, best_d = None, float("inf")
        for i in range(1, n):
            if stats[i, cv2.CC_STAT_AREA] < 0.15 * box_area:
                continue
            d = float(np.hypot(cents[i][0] - centre[0], cents[i][1] - centre[1]))
            if d < best_d:
                best, best_d = i, d
        return None if best is None else (labels == best).astype(np.uint8) * 255

    face = pick(bright)
    if face is None:
        return None
    if float((face > 0).sum()) > 1.6 * box_area:
        # 이웃 주사위와 붙었다. bbox를 조금 넓힌 영역만 남겨 다시 고른다.
        gate = np.zeros_like(face)
        mx, my = (bx2 - bx1) * 0.08, (by2 - by1) * 0.08
        cv2.rectangle(gate, (int(bx1 - mx), int(by1 - my)), (int(bx2 + mx), int(by2 + my)),
                      255, -1)
        face = pick(cv2.bitwise_and(bright, gate))
        if face is None:
            return None
    contours, _ = cv2.findContours(face, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return None
    return img, face, max(contours, key=cv2.contourArea)


def _face_pips(face: Any, outer: Any, p: DotCounterParams) -> list[tuple[Any, float, bool]]:
    """면 안의 눈: [(외곽선, 면 대비 넓이, 길쭉한가)]."""
    filled = np.zeros_like(face)
    cv2.drawContours(filled, [outer], -1, 255, -1)
    hull = np.zeros_like(face)
    cv2.drawContours(hull, [cv2.convexHull(outer)], -1, 255, -1)
    face_area = float((hull > 0).sum())
    if face_area <= 0:
        return []

    def holes(mask: Any) -> list[Any]:
        found, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        return list(found)

    pips: list[tuple[Any, float, bool]] = []
    for c in holes(cv2.bitwise_and(filled, cv2.bitwise_not(face))):
        ratio, circ, elongated = _shape(c, face_area)
        if p.face_pip_min <= ratio <= p.face_pip_max * 2 and (elongated or circ >= 0.5):
            pips.append((c, ratio, elongated))
    if not pips:
        return []
    unit = float(np.median([r for _c, r, e in pips if not e] or [r for _c, r, _e in pips]))
    # 면 가장자리에 걸려 윤곽을 파고든 눈 — 볼록 껍질 안, 면 윤곽 밖에 남는다.
    # 둥근 모서리·그림자 틈도 여기 남으므로 둥글고 크기가 맞는 것만 받는다.
    for c in holes(cv2.bitwise_and(hull, cv2.bitwise_not(filled))):
        ratio, circ, elongated = _shape(c, face_area)
        if not elongated and circ >= 0.7 and 0.5 * unit <= ratio <= 1.8 * unit:
            pips.append((c, ratio, False))
    return pips


def _count_with_face(frame_bgr: Any, bbox: BBox, p: DotCounterParams) -> int | None:
    found = _find_face(frame_bgr, bbox, p)
    if found is None:
        return None
    _img, face, outer = found
    pips = _face_pips(face, outer, p)
    if not pips:
        return None
    round_ratios = [r for _c, r, e in pips if not e] or [r for _c, r, _e in pips]
    unit = float(np.median(round_ratios))
    count = 0
    for _c, ratio, elongated in pips:
        if elongated and ratio > 1.7 * unit:
            count += min(3, int(round(ratio / unit)))  # 붙어 버린 눈
        elif ratio > p.face_pip_max:
            continue  # 눈이라기엔 너무 큰 구멍 — 가려진 부분·얼룩
        else:
            count += 1
    return count if 1 <= count <= 6 else None


class DotCounter:
    """주사위 눈 수 인식기.

    params 를 외부에서 주입하면 튜닝 도구와 연동 가능.
    """

    def __init__(self, params: DotCounterParams | None = None) -> None:
        self.params = params or DotCounterParams()

    def count(self, frame_bgr: Any, bbox: BBox) -> int | None:
        if self.params.method == "face":
            return _count_with_face(frame_bgr, bbox, self.params)
        if self.params.method == "components":
            crop = _crop_inset(frame_bgr, bbox, self.params.inset_ratio)
            if crop is None or crop.size == 0:
                return None
            return _count_with_components(crop, self.params)
        return self._count_hough(frame_bgr, bbox)

    def _count_hough(self, frame_bgr: Any, bbox: BBox) -> int | None:
        """예전 방식. 비교·튜닝 도구용으로 남긴다."""
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
        if self.params.method == "face":
            return self._debug_face(frame_bgr, bbox)
        if self.params.method == "components":
            return self._debug_components(frame_bgr, bbox)
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

    def _debug_components(self, frame_bgr: Any, bbox: BBox) -> tuple[int | None, Any]:
        """작업 이미지 위에 눈으로 인정한 덩어리(초록)와 버린 덩어리(빨강)를 그린다."""
        p = self.params
        blank = np.zeros((p.work_size, p.work_size, 3), dtype=np.uint8)
        crop = _crop_inset(frame_bgr, bbox, p.inset_ratio)
        if crop is None or crop.size == 0:
            return None, blank
        result = _count_with_components(crop, p)
        made = _pip_mask(crop, p)
        if made is None:
            vis = cv2.resize(crop, (p.work_size, p.work_size))
            cv2.putText(vis, "low", (4, p.work_size - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 0, 255), 1)
            return result, vis
        img, mask = made
        vis = img.copy()
        kept = {(round(c[0]), round(c[1])) for _a, c, _e in _pip_blobs(mask, p)}
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        for cnt in contours:
            m = cv2.moments(cnt)
            if m["m00"] == 0:
                continue
            c = (round(m["m10"] / m["m00"]), round(m["m01"] / m["m00"]))
            ok = any(abs(c[0] - k[0]) <= 1 and abs(c[1] - k[1]) <= 1 for k in kept)
            cv2.drawContours(vis, [cnt], -1, (0, 220, 0) if ok else (0, 0, 255), 1)
        label = str(result) if result is not None else "?"
        cv2.putText(vis, label, (4, p.work_size - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (0, 200, 255), 2)
        return result, vis

    def _debug_face(self, frame_bgr: Any, bbox: BBox) -> tuple[int | None, Any]:
        """면(초록으로 물들임)과 눈으로 센 구멍(빨강)을 그린다."""
        p = self.params
        result = _count_with_face(frame_bgr, bbox, p)
        found = _find_face(frame_bgr, bbox, p)
        if found is None:
            vis = np.zeros((p.face_work_size, p.face_work_size, 3), dtype=np.uint8)
            cv2.putText(vis, "no face", (4, p.face_work_size - 8), cv2.FONT_HERSHEY_SIMPLEX,
                        0.5, (0, 0, 255), 1)
            return result, vis
        img, face, outer = found
        vis = img.copy()
        tint = vis[face > 0].astype(np.float32) * 0.6 + np.array([0, 90, 0], np.float32)
        vis[face > 0] = tint.astype(np.uint8)
        for c, _r, _e in _face_pips(face, outer, p):
            cv2.drawContours(vis, [c], -1, (0, 0, 255), -1)
        label = str(result) if result is not None else "?"
        cv2.putText(vis, label, (4, vis.shape[0] - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.8,
                    (0, 200, 255), 2)
        return result, vis
