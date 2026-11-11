"""주사위 찾기 — 트레이 안의 흰 덩어리.

YOLO(weights/yacht_v4.pt)는 지금 쓰는 빨간 펠트 트레이에서 주사위를 제대로
못 잡는다. 2026-11-11 실물 14장에서:
  - 주사위 5개에 후보가 매번 10개 안팎 나왔고, 진짜와 가짜의 신뢰도가 섞여
    문턱으로 가를 수 없었다
  - 같은 주사위에 어긋난 박스가 둘씩 나왔다 (서로 덜 겹쳐 NMS에 안 걸린다)
  - 트레이 안 주사위도 자주 놓쳤고, 킵존(검은 칸) 주사위는 한 번도 못 잡았다

그런데 장면이 단순하다. **흰 주사위가 빨간 펠트·검은 트레이 위에 있다.** 세
채널 최솟값으로 보면 펠트(G·B가 낮다)와 트레이는 어둡고 주사위는 밝다. 그래서
트레이 영역 안의 밝은 덩어리가 곧 주사위다. 같은 14장에서 70개 중 70개를
찾았다(킵존 포함).

YOLO는 트레이·굴림통을 찾는 데만 쓴다. 트레이 박스는 "어느 어두운 덩어리가
트레이인가"를 고르는 데 쓴다 — 화면에 노트북 키보드처럼 더 큰 어두운 덩어리가
있을 수 있다.

순서:
  1. 960px로 줄여 세 채널 최솟값을 Otsu로 가른다 (어두움 = 트레이·펠트)
  2. 트레이 박스 중심을 덮는 어두운 덩어리 = 트레이. 외곽을 채워 트레이 영역
  3. 트레이 영역 안의 밝은 덩어리, 그 안의 구멍(눈)은 메운다
  4. 크기·흰색(채도)·네모난 정도로 거른다 — 손가락은 채도에서 떨어진다
  5. 두 배 넘게 큰 덩어리는 붙은 주사위로 보고 나눈다
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

from vision.schemas import BBox, YoloDet


@dataclass
class DiceFinderParams:
    work_width: int = 960
    # 주사위 하나의 넓이 범위 (트레이 영역 대비)
    min_area_ratio: float = 0.002
    max_area_ratio: float = 0.05
    # 흰색 판정. HSV 채도 평균이 이보다 높으면 주사위가 아니다(손·물건).
    max_saturation: float = 70.0
    # YOLO가 같은 자리에 주사위 박스를 냈으면(hint) 채도 문턱을 이만큼까지 푼다.
    # 조명·화이트밸런스가 틀어지면 흰 주사위도 채도가 70을 넘는다 — 6월 녹화본에서
    # 75~89가 나와 주사위가 0개로 떨어졌다. 두 검출기가 같은 덩어리를 가리키면
    # 색이 조금 틀어져도 주사위로 본다. 손가락은 YOLO가 주사위로 내지 않는다.
    max_saturation_hinted: float = 140.0
    # 트레이 기준 박스. 이만큼 연속으로 같은 자리에 잡혀야 기준으로 삼는다.
    ref_confirm_frames: int = 10
    # 기준과 이 IoU 이상 겹치면 "같은 트레이"로 본다.
    ref_iou: float = 0.9
    # 기준과 다른 박스가 이만큼 연속으로 **서로 같게** 나오면 트레이가 옮겨진 것 —
    # 기준을 새로 잡는다.
    ref_reset_frames: int = 60
    # 회전 최소 사각형 대비 채움 비율. 주사위 면은 0.8 안팎, 모서리가 둥글어도 0.65+.
    min_rect_fill: float = 0.6


class DiceFinder:
    """프레임 → 주사위 YoloDet 목록. 트레이를 못 찾으면 빈 목록."""

    def __init__(self, params: DiceFinderParams | None = None) -> None:
        self.params = params or DiceFinderParams()
        # 트레이 박스를 한 프레임 놓쳐도 직전 것으로 이어 간다. 트레이는 움직이지 않는다.
        self._last_tray: BBox | None = None
        # 트레이 기준 박스 — 여러 프레임 같은 자리에 잡힌 뒤에만 선다.
        #
        # 트레이는 "어두운 덩어리"로 찾는데, 손·팔 그림자가 트레이와 굴림통(역시
        # 어둡다)을 잇는 순간 덩어리가 하나로 붙어 트레이 박스가 굴림통까지
        # 부풀었다. 그러면 굴림통이 "트레이 안"으로 판정되어, 굴림통 없이 손으로
        # 주사위만 건드려도 굴림 확정이 났다 (6월 녹화본 87초: 같은 눈으로 두 번).
        # 기준이 서면 덩어리를 기준 박스 안으로 잘라 쓰고, 밖에 알리는 트레이
        # 박스도 기준으로 고정한다.
        self._ref_tray: BBox | None = None
        self._pending: BBox | None = None
        self._pending_count = 0

    @property
    def tray(self) -> BBox | None:
        """트레이 영역. 기준이 섰으면 기준 박스, 아니면 마지막으로 찾은 덩어리의 박스."""
        return self._ref_tray or self._last_tray

    def _update_ref(self, region: BBox) -> None:
        p = self.params
        if self._ref_tray is not None and region.iou(self._ref_tray) >= p.ref_iou:
            self._pending, self._pending_count = None, 0
            return
        if self._pending is not None and region.iou(self._pending) >= 0.95:
            self._pending_count += 1
        else:
            self._pending, self._pending_count = region, 1
        need = p.ref_confirm_frames if self._ref_tray is None else p.ref_reset_frames
        if self._pending_count >= need:
            self._ref_tray = BBox(
                self._pending.x1, self._pending.y1, self._pending.x2, self._pending.y2,
                0.5, "tray",
            )
            self._pending, self._pending_count = None, 0

    def find(
        self,
        frame_bgr: Any,
        trays: list[BBox],
        yolo_dice: list[YoloDet] | None = None,
    ) -> list[YoloDet]:
        """trays: 이번 프레임 YOLO의 tray·tray_inner 박스 전부 (없어도 된다).

        yolo_dice: 이번 프레임 YOLO의 dice 검출 (없어도 된다). 두 가지로 쓴다.
          - 덩어리 판정의 보조 증거 — YOLO가 같은 자리를 주사위라고 하면 채도
            문턱을 푼다 (DiceFinderParams.max_saturation_hinted)
          - 트레이 영역을 아예 못 찾았을 때의 대체 결과 — 빈 목록 대신 YOLO
            검출을 그대로 돌려준다
        """
        hints = [d.bbox for d in (yolo_dice or [])]
        candidates = list(trays)
        if self._last_tray is not None:
            candidates.append(self._last_tray)
        if self._ref_tray is not None:
            candidates.append(self._ref_tray)
        if not candidates:
            return list(yolo_dice or [])
        boxes, region = find_dice_in(frame_bgr, candidates, self.params, hints, self._ref_tray)
        if region is None:
            return list(yolo_dice or [])
        self._update_ref(region)
        # 신뢰도 0.5로 기억한다 — 확실한 YOLO 검출(0.5 넘게)이 나오면 그쪽이
        # 먼저 검토되어, 처음에 잘못 골랐어도 바로잡힌다.
        self._last_tray = BBox(region.x1, region.y1, region.x2, region.y2, 0.5, "tray")
        return [YoloDet(cls_name="dice", bbox=b) for b in boxes]


def find_dice(frame_bgr: Any, tray: BBox, p: DiceFinderParams | None = None) -> list[BBox]:
    return find_dice_in(frame_bgr, [tray], p)[0]


def find_dice_in(
    frame_bgr: Any,
    trays: list[BBox],
    p: DiceFinderParams | None = None,
    hints: list[BBox] | None = None,
    clip: BBox | None = None,
) -> tuple[list[BBox], BBox | None]:
    """(주사위 박스들, 찾은 트레이 영역의 박스). 트레이를 못 찾으면 ([], None).

    hints: YOLO dice 박스(정규화). 덩어리 중심이 그 안에 들면 채도 문턱을 푼다.
    clip:  트레이 기준 박스. 주면 트레이 덩어리를 이 박스 안으로 자른다 —
           그림자로 굴림통·팔과 붙어 부푼 부분을 버린다. 돌려주는 영역 박스는
           자르기 **전** 것이다 (기준 갱신 판단용).
    """
    p = p or DiceFinderParams()
    h, w = frame_bgr.shape[:2]
    s = p.work_width / w
    small = cv2.resize(frame_bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    mn = cv2.GaussianBlur(small.min(axis=2), (5, 5), 0)
    thresh, dark = cv2.threshold(mn, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    dark = cv2.morphologyEx(dark, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))

    # 트레이 = 가장 믿을 만한 후보 박스의 중심을 품은 어두운 덩어리.
    #
    # YOLO는 트레이 박스를 엉뚱한 곳(노트북)에 하나 더 내기도 하고, 트레이를
    # 놓치고 안쪽 펠트(tray_inner)만 잡기도 한다(2026-11-11 실물). 그래서 후보를
    # 전부 받아 신뢰도 높은 것부터 본다. 덩어리 크기로 고르면 노트북처럼 더 큰
    # 어두운 물체가 이긴다. 후보 박스가 덩어리 안에 대부분 들어가야 한다(cover) —
    # 안쪽 펠트 박스는 트레이 덩어리 안에 쏙 들어간다.
    n, labels, stats, _c = cv2.connectedComponentsWithStats(dark, connectivity=8)
    tray_id = None
    for t in sorted(trays, key=lambda b: -b.conf):
        tx1, ty1, tx2, ty2 = t.x1 * sw, t.y1 * sh, t.x2 * sw, t.y2 * sh
        t_area = max(1.0, (tx2 - tx1) * (ty2 - ty1))
        ccx, ccy = int((tx1 + tx2) / 2), int((ty1 + ty2) / 2)
        if not (0 <= ccx < sw and 0 <= ccy < sh):
            continue
        # 중심이 주사위 위면 그 주변(트레이 쪽)을 본다: 중심 근처 어두운 픽셀의 덩어리.
        y0, y1_ = max(0, ccy - 12), min(sh, ccy + 13)
        x0, x1_ = max(0, ccx - 12), min(sw, ccx + 13)
        ids = labels[y0:y1_, x0:x1_]
        ids = ids[ids > 0]
        if ids.size == 0:
            continue
        i = int(np.bincount(ids).argmax())
        x, y, bw, bh, _area = stats[i]
        ix = max(0.0, min(tx2, x + bw) - max(tx1, x))
        iy = max(0.0, min(ty2, y + bh) - max(ty1, y))
        if (ix * iy) / t_area >= 0.7 and bw * bh >= 0.5 * t_area:
            tray_id = i
            break
    if tray_id is None:
        return [], None
    tray_mask = (labels == tray_id).astype(np.uint8) * 255
    outer, _ = cv2.findContours(tray_mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    region = np.zeros_like(tray_mask)
    cv2.drawContours(region, outer, -1, 255, -1)
    if clip is not None:
        cx1, cy1 = max(0, int(clip.x1 * sw) - 2), max(0, int(clip.y1 * sh) - 2)
        cx2, cy2 = min(sw, int(clip.x2 * sw) + 3), min(sh, int(clip.y2 * sh) + 3)
        keep = np.zeros_like(region)
        keep[cy1:cy2, cx1:cx2] = 255
        region = cv2.bitwise_and(region, keep)
    region_area = float((region > 0).sum())
    if region_area <= 0:
        return [], None
    rx, ry, rw_, rh_ = stats[tray_id, 0], stats[tray_id, 1], stats[tray_id, 2], stats[tray_id, 3]
    region_box = BBox(rx / sw, ry / sh, (rx + rw_) / sw, (ry + rh_) / sh, 1.0, "tray")

    # 트레이 안의 밝은 덩어리. 눈(구멍)은 메운다 — 대각선의 눈이 면을 가르지 않게.
    bright = np.where(mn > thresh, 255, 0).astype(np.uint8)
    bright = cv2.bitwise_and(bright, region)
    bright = cv2.morphologyEx(bright, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    blobs, _ = cv2.findContours(bright, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    faces = np.zeros_like(bright)
    cv2.drawContours(faces, blobs, -1, 255, -1)
    sat = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)[..., 1]

    n2, lab2, st2, _c2 = cv2.connectedComponentsWithStats(faces, connectivity=8)
    cands: list[tuple[int, float, tuple[float, float]]] = []
    for i in range(1, n2):
        area = float(st2[i, cv2.CC_STAT_AREA])
        ratio = area / region_area
        if ratio < p.min_area_ratio or ratio > p.max_area_ratio:
            continue
        mask_i = lab2 == i
        sat_mean = float(sat[mask_i].mean())
        if sat_mean > p.max_saturation:
            bx, by = st2[i, cv2.CC_STAT_LEFT], st2[i, cv2.CC_STAT_TOP]
            bcx = (bx + st2[i, cv2.CC_STAT_WIDTH] / 2) / sw
            bcy = (by + st2[i, cv2.CC_STAT_HEIGHT] / 2) / sh
            hinted = any(hb.x1 <= bcx <= hb.x2 and hb.y1 <= bcy <= hb.y2 for hb in hints or [])
            if not hinted or sat_mean > p.max_saturation_hinted:
                continue
        ys, xs = np.nonzero(mask_i)
        (_rc, (rw, rh), _ang) = cv2.minAreaRect(np.column_stack([xs, ys]).astype(np.float32))
        aspect = max(rw, rh) / max(1.0, min(rw, rh))
        cands.append((i, area, (rw * rh, aspect)))
    if not cands:
        return [], region_box

    unit = float(np.median([a for _i, a, _r in cands]))
    out: list[BBox] = []
    for i, area, (rect_area, aspect) in cands:
        ys, xs = np.nonzero(lab2 == i)
        pieces = 1
        # 붙은 주사위: 두 배 넘게 크거나, 1.6배 이상이면서 길쭉할 때만 나눈다.
        # 옆면이 함께 보이는 주사위(킵존 벽에 기댄 것)는 1.3배쯤이라 나누지 않는다.
        if area > 2.4 * unit or (area > 1.6 * unit and aspect > 1.45):
            pieces = min(4, int(round(area / unit)))
        if pieces <= 1:
            if area < 0.45 * unit or area / max(1.0, rect_area) < p.min_rect_fill:
                continue
            groups = [np.column_stack([xs, ys])]
        else:
            pts = np.column_stack([xs, ys]).astype(np.float32)
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.5)
            _cmp, km, _ctr = cv2.kmeans(pts, pieces, None, criteria, 5, cv2.KMEANS_PP_CENTERS)
            groups = [pts[km.ravel() == j] for j in range(pieces)]
        for g in groups:
            if len(g) == 0:
                continue
            x1, y1 = g.min(axis=0)
            x2, y2 = g.max(axis=0) + 1
            out.append(BBox(float(x1 / sw), float(y1 / sh), float(x2 / sw), float(y2 / sh),
                            0.9, "dice"))
    return out, region_box
