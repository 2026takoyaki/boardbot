"""DotCounter 단위 테스트.

opencv-python 필요. 합성 이미지(흰 사각형 + 검은 원)로 1~6 검증.
"""

from __future__ import annotations

import cv2
import numpy as np
import pytest

from vision.detectors.dot_counter import DotCounter
from vision.schemas import BBox


def _make_dice_image(pip_count: int, size: int = 180) -> tuple[np.ndarray, BBox]:
    """흰 배경 + 검은 원 pip_count 개 합성 이미지 + 전체 BBox."""
    img = np.ones((size, size, 3), dtype=np.uint8) * 240  # 밝은 회색 배경

    # pip 위치 패턴 (정규화 중심 좌표) — 원 간격 충분히 확보
    patterns: dict[int, list[tuple[float, float]]] = {
        1: [(0.5, 0.5)],
        2: [(0.3, 0.3), (0.7, 0.7)],
        3: [(0.3, 0.3), (0.5, 0.5), (0.7, 0.7)],
        4: [(0.3, 0.3), (0.7, 0.3), (0.3, 0.7), (0.7, 0.7)],
        5: [(0.3, 0.3), (0.7, 0.3), (0.5, 0.5), (0.3, 0.7), (0.7, 0.7)],
        6: [(0.25, 0.22), (0.75, 0.22), (0.25, 0.5), (0.75, 0.5), (0.25, 0.78), (0.75, 0.78)],
    }
    radius = max(5, size // 18)  # 크기 대비 작은 원으로 간격 확보
    for cx_r, cy_r in patterns[pip_count]:
        cx = int(cx_r * size)
        cy = int(cy_r * size)
        cv2.circle(img, (cx, cy), radius, (30, 30, 30), -1)

    bbox = BBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0, conf=0.99, cls_name="dice")
    return img, bbox


@pytest.mark.parametrize("pip_count", [1, 2, 3, 4, 5, 6])
def test_dot_counter_clean_image(pip_count: int) -> None:
    """깨끗한 합성 이미지에서 pip_count 정확히 인식."""
    counter = DotCounter()
    img, bbox = _make_dice_image(pip_count, size=120)
    result = counter.count(img, bbox)
    # 합성 이미지 특성상 ±1 허용 (HoughCircles 파라미터 민감)
    assert result is not None, f"pip={pip_count}: result was None"
    assert abs(result - pip_count) <= 1, f"pip={pip_count}: got {result}"


def test_dot_counter_empty_bbox_returns_none() -> None:
    """빈 BBox는 None 반환."""
    counter = DotCounter()
    img = np.ones((100, 100, 3), dtype=np.uint8) * 200
    bbox = BBox(x1=0.5, y1=0.5, x2=0.5, y2=0.5, conf=0.9, cls_name="dice")
    assert counter.count(img, bbox) is None


def test_dot_counter_noisy_image_does_not_crash() -> None:
    """노이즈 이미지는 None 또는 1~6 반환 (크래시 없음)."""
    counter = DotCounter()
    rng = np.random.default_rng(42)
    img = rng.integers(0, 255, (100, 100, 3), dtype=np.uint8)
    bbox = BBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0, conf=0.9, cls_name="dice")
    result = counter.count(img, bbox)
    assert result is None or 1 <= result <= 6


# ── 면 찾기 방식 (기본) ─────────────────────────────────────────────────────


@pytest.mark.parametrize("pip_count", [1, 2, 3, 4, 5, 6])
def test_components_exact_on_clean_image(pip_count: int) -> None:
    """깨끗한 면은 오차 없이 맞혀야 한다 (예전 방식은 ±1을 허용했다)."""
    img, bbox = _make_dice_image(pip_count, size=120)
    assert DotCounter().count(img, bbox) == pip_count


def test_components_accuracy_on_synthetic_table() -> None:
    """펠트 위 회전·흐림·조명·빛 반사·빨간 1눈이 섞인 주사위 360개.

    실물 정확도가 아니다(그건 tools/dice_dataset.py로 잰다). 로직이 흔한
    교란에 무너지지 않는지를 본다. 오답은 미판정보다 훨씬 나쁘다 — 미판정은
    다수결 버퍼가 흡수하지만 오답은 표를 갉아먹는다.
    """
    from tests.dice_synth import render

    rng = np.random.default_rng(7)
    counter = DotCounter()
    right = wrong = 0
    for pips in range(1, 7):
        for _ in range(60):
            frame, bbox = render(pips, rng)
            got = counter.count(frame, bbox)
            if got == pips:
                right += 1
            elif got is not None:
                wrong += 1
    assert right / 360 >= 0.95
    assert wrong / 360 <= 0.02


def test_components_rejects_blank_face() -> None:
    """눈이 안 보이는 면(가려짐·과노출)은 판정하지 않는다."""
    img = np.full((120, 120, 3), 235, np.uint8)
    bbox = BBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0, conf=0.9, cls_name="dice")
    assert DotCounter().count(img, bbox) is None


def test_components_reads_red_one_pip() -> None:
    """빨간 1눈 — 회색 변환으로는 면과 잘 안 갈린다. 채널 최솟값으로 본다."""
    img = np.full((120, 120, 3), 240, np.uint8)
    cv2.circle(img, (60, 60), 14, (40, 40, 210), -1)
    bbox = BBox(x1=0.0, y1=0.0, x2=1.0, y2=1.0, conf=0.9, cls_name="dice")
    assert DotCounter().count(img, bbox) == 1


def test_legacy_hough_still_available() -> None:
    from vision.detectors.dot_counter import DotCounterParams

    img, bbox = _make_dice_image(3, size=120)
    got = DotCounter(DotCounterParams(method="hough")).count(img, bbox)
    assert got is None or 1 <= got <= 6


@pytest.mark.parametrize("shift", [-0.25, -0.15, 0.15, 0.25])
def test_face_survives_shifted_bbox(shift: float) -> None:
    """YOLO 박스가 밀려도 면을 직접 찾으므로 결과가 같아야 한다.

    실물 화면(2026-11-11)에서 이웃 주사위와 붙은 주사위의 박스가 한쪽으로
    밀려 눈 열이 잘렸다. 박스 안쪽만 세던 방식은 15%만 밀어도 무너졌다.
    """
    from tests.dice_synth import render

    rng = np.random.default_rng(21)
    counter = DotCounter()
    right = 0
    for pips in range(1, 7):
        for _ in range(10):
            frame, b = render(pips, rng)
            dx, dy = (b.x2 - b.x1) * shift, (b.y2 - b.y1) * shift
            moved = BBox(b.x1 + dx, b.y1 + dy, b.x2 + dx, b.y2 + dy, b.conf, b.cls_name)
            right += counter.count(frame, moved) == pips
    assert right / 60 >= 0.9


def test_face_ignores_touching_neighbour() -> None:
    """붙어 있는 이웃 주사위의 눈을 같이 세지 않는다."""
    frame = np.full((300, 400, 3), (40, 30, 150), np.uint8)  # 빨간 펠트
    cv2.rectangle(frame, (100, 100), (170, 170), (235, 235, 235), -1)  # 2눈
    cv2.rectangle(frame, (171, 100), (241, 170), (235, 235, 235), -1)  # 붙은 6눈
    for cx, cy in ((118, 118), (152, 152)):
        cv2.circle(frame, (cx, cy), 7, (25, 25, 25), -1)
    for cx in (189, 223):
        for cy in (115, 135, 155):
            cv2.circle(frame, (cx, cy), 6, (25, 25, 25), -1)
    bbox = BBox(100 / 400, 100 / 300, 170 / 400, 170 / 300, 0.9, "dice")
    assert DotCounter().count(frame, bbox) == 2
