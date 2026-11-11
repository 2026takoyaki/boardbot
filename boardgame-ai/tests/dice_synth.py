"""합성 주사위 이미지. 눈 세기 로직을 하드웨어 없이 검증하는 데 쓴다.

실물 정확도는 tools/dice_dataset.py 로 찍은 사진으로 따로 잰다. 여기서는
"흰 면 위의 검은 원을 세는 로직이 회전·흐림·조명 변화에 견디는가"만 본다.
"""

from __future__ import annotations

import math

import cv2
import numpy as np

from vision.schemas import BBox

# 면 위 눈 위치 (면 한 변을 1로 본 좌표)
_L, _C, _R = 0.25, 0.5, 0.75
LAYOUT = {
    1: [(_C, _C)],
    2: [(_L, _L), (_R, _R)],
    3: [(_L, _L), (_C, _C), (_R, _R)],
    4: [(_L, _L), (_R, _L), (_L, _R), (_R, _R)],
    5: [(_L, _L), (_R, _L), (_C, _C), (_L, _R), (_R, _R)],
    6: [(_L, _L), (_L, _C), (_L, _R), (_R, _L), (_R, _C), (_R, _R)],
}


def render(pips: int, rng: np.random.Generator, frame_hw=(720, 1280)):
    """(frame_bgr, bbox) — 펠트 위에 회전된 주사위 하나."""
    h, w = frame_hw
    frame = np.zeros((h, w, 3), np.uint8)
    frame[:] = (rng.integers(30, 60), rng.integers(70, 110), rng.integers(30, 60))

    side = int(rng.integers(38, 80))  # 화면 속 주사위 크기(px)
    s = side * 4  # 고해상도로 그린 뒤 줄인다
    face = np.full((s, s, 3), int(rng.integers(215, 250)), np.uint8)
    pip_r = s * float(rng.uniform(0.075, 0.095))
    color = (40, 40, 200) if pips == 1 and rng.random() < 0.5 else (25, 25, 25)
    r1 = pip_r * (1.5 if pips == 1 else 1.0)
    for x, y in LAYOUT[pips]:
        cv2.circle(face, (int(x * s), int(y * s)), int(r1), color, -1, cv2.LINE_AA)
    # 모서리 둥글림 느낌 — 테두리를 살짝 어둡게
    cv2.rectangle(face, (0, 0), (s - 1, s - 1), (170, 170, 170), max(2, s // 40))
    if rng.random() < 0.4:  # 빛 반사
        gx, gy = int(rng.uniform(0.2, 0.8) * s), int(rng.uniform(0.2, 0.8) * s)
        glare = face.copy()
        cv2.circle(glare, (gx, gy), int(s * 0.08), (255, 255, 255), -1)
        face = cv2.addWeighted(face, 0.6, glare, 0.4, 0)
    face = cv2.resize(face, (side, side), interpolation=cv2.INTER_AREA)

    angle = float(rng.uniform(0, 90))
    cx, cy = int(rng.integers(200, w - 200)), int(rng.integers(150, h - 150))
    m = cv2.getRotationMatrix2D((side / 2, side / 2), angle, 1.0)
    m[0, 2] += cx - side / 2
    m[1, 2] += cy - side / 2
    warped = cv2.warpAffine(face, m, (w, h), flags=cv2.INTER_LINEAR)
    mask = cv2.warpAffine(np.full((side, side), 255, np.uint8), m, (w, h))
    # 그림자
    shadow = cv2.GaussianBlur(mask, (0, 0), side * 0.08)
    shadow = np.roll(shadow, (int(side * 0.06), int(side * 0.06)), axis=(0, 1))
    frame = (frame * (1 - 0.35 * (shadow[..., None] / 255.0))).astype(np.uint8)
    frame[mask > 0] = warped[mask > 0]

    gain = float(rng.uniform(0.75, 1.15))
    frame = np.clip(frame.astype(np.float32) * gain + rng.normal(0, 4, frame.shape), 0, 255)
    frame = frame.astype(np.uint8)
    if rng.random() < 0.5:
        frame = cv2.GaussianBlur(frame, (3, 3), 0)

    # YOLO 박스 = 회전된 주사위의 외접 사각형 + 약간의 오차
    half = side * (abs(math.cos(math.radians(angle))) + abs(math.sin(math.radians(angle)))) / 2
    jitter = rng.uniform(-0.06, 0.06, 4) * side
    x1, y1 = cx - half + jitter[0], cy - half + jitter[1]
    x2, y2 = cx + half + jitter[2], cy + half + jitter[3]
    bbox = BBox(x1 / w, y1 / h, x2 / w, y2 / h, 0.9, "dice")
    return frame, bbox
