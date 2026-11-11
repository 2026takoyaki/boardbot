"""DiceFinder — 트레이 안의 흰 덩어리를 주사위로 찾는다.

실물(2026-11-11)의 구성을 흉내 낸 합성 장면: 흰 테이블 위 검은 트레이, 안쪽
빨간 펠트, 오른쪽 검은 킵존 칸. 옆에 노트북처럼 더 큰 어두운 물체를 둔다.
"""

from __future__ import annotations

import cv2
import numpy as np

from vision.detectors.dice_finder import DiceFinder, find_dice_in
from vision.schemas import BBox

W, H = 1920, 1080


def _die(img, cx, cy, side=52, angle=0.0, pips=3):
    rect = ((cx, cy), (side, side), angle)
    pts = cv2.boxPoints(rect).astype(np.int32)
    cv2.fillPoly(img, [pts], (238, 238, 238))
    for k in range(pips):
        off = (k - (pips - 1) / 2) * side * 0.25
        cv2.circle(img, (int(cx + off), int(cy + off)), max(3, side // 12), (25, 25, 25), -1)


def _scene():
    img = np.full((H, W, 3), (215, 215, 212), np.uint8)  # 흰 테이블
    cv2.rectangle(img, (60, 80), (760, 700), (40, 40, 40), -1)  # 노트북 (더 큰 어두운 물체)
    cv2.rectangle(img, (900, 400), (1500, 1000), (30, 30, 30), -1)  # 트레이 (검은 테두리)
    cv2.rectangle(img, (960, 460), (1380, 940), (30, 30, 150), -1)  # 빨간 펠트
    dice = [(1050, 560, 0), (1250, 600, 30), (1100, 820, 45), (1300, 860, 10)]
    for cx, cy, ang in dice:
        _die(img, cx, cy, angle=ang)
    _die(img, 1440, 700, angle=0)  # 킵존(검은 칸) 주사위
    return img, len(dice) + 1


def _box(x1, y1, x2, y2, conf):
    return BBox(x1 / W, y1 / H, x2 / W, y2 / H, conf, "tray")


def test_finds_all_dice_including_keep_zone() -> None:
    img, n = _scene()
    found, region = find_dice_in(img, [_box(890, 390, 1510, 1010, 0.9)])
    assert len(found) == n
    assert region is not None


def test_ignores_bogus_tray_box_on_laptop() -> None:
    """YOLO가 노트북에도 트레이 박스를 냈을 때 — 신뢰도 높은 쪽(진짜)을 따른다."""
    img, n = _scene()
    trays = [_box(60, 80, 760, 700, 0.41), _box(960, 460, 1380, 940, 0.84)]  # 가짜, 안쪽 펠트
    found, _ = find_dice_in(img, trays)
    assert len(found) == n


def test_remembers_tray_when_yolo_misses_it() -> None:
    img, n = _scene()
    finder = DiceFinder()
    assert len(finder.find(img, [_box(890, 390, 1510, 1010, 0.9)])) == n
    assert len(finder.find(img, [])) == n  # 이번 프레임엔 트레이 박스가 없다


def test_skin_coloured_blob_is_not_a_die() -> None:
    img, n = _scene()
    cv2.circle(img, (1180, 700), 30, (120, 160, 220), -1)  # 손가락 끝 (채도 높음)
    found, _ = find_dice_in(img, [_box(890, 390, 1510, 1010, 0.9)])
    assert len(found) == n


def test_no_tray_candidates_means_nothing() -> None:
    img, _ = _scene()
    assert find_dice_in(img, [])[0] == []


# ── YOLO 보조 증거 (hybrid) ───────────────────────────────────────────────────


def _tinted_scene():
    """조명·화이트밸런스가 틀어져 주사위가 푸르스름한 장면 (채도 70 초과)."""
    img, n = _scene()
    white = np.all(img > 200, axis=2) & (np.abs(img[..., 0].astype(int) - 238) < 3)
    img[white] = (238, 200, 150)  # BGR — 채도 약 94
    return img, n


def _dice_hints():
    from vision.schemas import YoloDet

    centers = [(1050, 560), (1250, 600), (1100, 820), (1300, 860)]  # 킵존 것은 YOLO가 못 본다
    return [
        YoloDet(cls_name="dice", bbox=BBox((x - 30) / W, (y - 30) / H, (x + 30) / W, (y + 30) / H,
                                           0.6, "dice"))
        for x, y in centers
    ]


def test_tinted_dice_need_yolo_agreement() -> None:
    img, n = _tinted_scene()
    tray = [_box(890, 390, 1510, 1010, 0.9)]
    assert len(DiceFinder().find(img, tray)) == 0  # 색만 보면 주사위가 아니다
    assert len(DiceFinder().find(img, tray, _dice_hints())) == n - 1  # YOLO가 가리킨 4개


def test_skin_blob_stays_rejected_even_with_hints() -> None:
    img, n = _scene()
    cv2.circle(img, (1180, 700), 30, (120, 160, 220), -1)  # 손가락 끝
    found = DiceFinder().find(img, [_box(890, 390, 1510, 1010, 0.9)], _dice_hints())
    assert len(found) == n


def test_falls_back_to_yolo_dice_when_tray_is_never_found() -> None:
    img, _ = _scene()
    hints = _dice_hints()
    assert len(DiceFinder().find(img, [], hints)) == len(hints)


def test_tray_box_does_not_balloon_when_shadow_bridges_to_the_cup() -> None:
    """팔 그림자가 트레이와 굴림통을 이어도 트레이 박스는 그대로다."""
    img, n = _scene()
    cv2.circle(img, (1700, 500), 110, (25, 25, 25), -1)  # 굴림통 (어둡다)
    finder = DiceFinder()
    tray = [_box(890, 390, 1510, 1010, 0.9)]
    for _ in range(finder.params.ref_confirm_frames + 1):
        finder.find(img, tray)
    before = finder.tray
    assert before is not None and before.x2 < 1520 / W
    bridged = img.copy()
    cv2.line(bridged, (1500, 520), (1620, 500), (40, 40, 40), 40)  # 그림자
    assert len(finder.find(bridged, tray)) == n
    after = finder.tray
    assert after is not None and abs(after.x2 - before.x2) < 1e-6
