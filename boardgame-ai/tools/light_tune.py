"""조명 설정별 주사위 인식 품질 측정.

조도를 얼마로 잡을지는 눈으로 정할 수 없다. 사람 눈에 좋아 보이는 밝기와
YOLO가 잘 읽는 밝기는 다르고, 특히 과노출은 눈으로 잘 안 보이는데 pip 대비를
통째로 날린다. 그래서 설정을 바꿔가며 실제로 재고 표로 비교한다.

    # 기본 스윕 — 밝기 5단계 × 색온도 3단계
    python -m tools.light_tune

    # 지금 조명 그대로 한 번만 측정 (전구를 건드리지 않는다)
    python -m tools.light_tune --no-light

    # 밝기만 훑기
    python -m tools.light_tune --brightness 40,55,70,85,100 --kelvin 4000

준비:
    주사위 5개를 트레이 안에 **서로 떨어뜨려** 놓고, 측정하는 동안 손대지 않는다.
    실제 게임과 같은 위치·같은 카메라 높이여야 의미가 있다.

읽는 법:
    5개검출   높을수록 좋다. 이게 낮으면 굴림이 확정되지 않는다.
    눈인식     높을수록 좋다. 이게 낮으면 "읽지 못한 주사위가 있습니다"가 뜬다.
    과노출     낮을수록 좋다. 주사위 표면이 타서 눈이 안 보이는 정도.
    흔들림     낮을수록 좋다. DiceManager의 motion_threshold와 같은 척도라
              이 값이 임계값을 넘으면 정지 판정이 계속 리셋된다.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import statistics
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from dotenv import load_dotenv

from bulb import LightConfig, build_driver
from bulb.driver.base import LightDriver
from core.constants import DEFAULT_PARAMS
from vision.detectors.dot_counter import DotCounter
from vision.detectors.yolo_detector import YoloDetector
from vision.schemas import BBox, YoloDet

# 이 값 이상이면 픽셀이 탔다고 본다. 흰 주사위 표면이 여기 걸리면 검은 눈과의
# 대비가 남아도 Hough가 원 경계를 못 잡는다.
_CLIP_LEVEL = 250

# 프레임 사이에서 같은 주사위로 볼 최대 중심 이동 (정규화). 이보다 멀면 다른
# 주사위로 본다 — 정지 상태를 재는 것이므로 넉넉할 필요가 없다.
_MATCH_RADIUS = 0.05


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="조명 설정별 주사위 인식 품질 측정")
    p.add_argument("--brightness", default="40,55,70,85,100", help="쉼표로 구분한 밝기 목록")
    p.add_argument("--kelvin", default="2700,4000,5500", help="쉼표로 구분한 색온도 목록")
    p.add_argument("--frames", type=int, default=45, help="설정당 측정 프레임 수")
    p.add_argument("--settle", type=float, default=2.5,
                   help="조명 변경 후 대기 초. 카메라 자동노출이 따라잡을 시간이 필요하다")
    p.add_argument("--weights", default="weights/yacht_v4.pt")
    p.add_argument("--conf", type=float, default=0.35, help="YOLO 신뢰도 임계값")
    p.add_argument("--camera", type=int, default=int(os.environ.get("CAMERA_INDEX", "0")))
    p.add_argument("--no-light", action="store_true",
                   help="전구를 건드리지 않고 현재 조명에서 한 번만 측정")
    return p.parse_args()


def _ints(raw: str) -> list[int]:
    return [int(x) for x in raw.split(",") if x.strip()]


def _split(dets: list[YoloDet]) -> tuple[BBox | None, list[YoloDet]]:
    tray = None
    dice: list[YoloDet] = []
    for d in dets:
        if d.cls_name == "tray":
            tray = d.bbox
        elif d.cls_name == "dice":
            dice.append(d)
    return tray, dice


def _clip_ratio(frame: Any, bbox: BBox) -> float:
    """주사위 영역에서 흰색으로 타버린 픽셀 비율."""
    h, w = frame.shape[:2]
    x1, y1 = max(0, int(bbox.x1 * w)), max(0, int(bbox.y1 * h))
    x2, y2 = min(w, int(bbox.x2 * w)), min(h, int(bbox.y2 * h))
    if x2 <= x1 or y2 <= y1:
        return 0.0
    gray = cv2.cvtColor(frame[y1:y2, x1:x2], cv2.COLOR_BGR2GRAY)
    return float(np.count_nonzero(gray >= _CLIP_LEVEL)) / gray.size


def _motion_score(history: list[tuple[float, float]]) -> float:
    """DiceManager._compute_motion_score와 같은 계산.

    같은 척도여야 측정값을 motion_threshold와 직접 비교할 수 있다.
    """
    if len(history) < 5:
        return float("inf")
    dists = [
        ((history[i][0] - history[i - 1][0]) ** 2 + (history[i][1] - history[i - 1][1]) ** 2) ** 0.5
        for i in range(1, len(history))
    ]
    mean = sum(dists) / len(dists)
    return (sum((d - mean) ** 2 for d in dists) / len(dists)) ** 0.5


class _Sample:
    """한 조명 설정에서의 측정 결과."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.dice_counts: list[int] = []
        self.confs: list[float] = []
        self.clips: list[float] = []
        self.pip_ok = 0
        self.pip_total = 0
        self.jitters: list[float] = []
        self.exposure: list[float] = []

    @property
    def five_rate(self) -> float:
        if not self.dice_counts:
            return 0.0
        return sum(1 for c in self.dice_counts if c >= 5) / len(self.dice_counts)

    @property
    def pip_rate(self) -> float:
        return self.pip_ok / self.pip_total if self.pip_total else 0.0

    def row(self) -> str:
        mean_dice = statistics.mean(self.dice_counts) if self.dice_counts else 0.0
        conf = statistics.mean(self.confs) if self.confs else 0.0
        clip = statistics.mean(self.clips) if self.clips else 0.0
        jit = statistics.median(self.jitters) if self.jitters else float("nan")
        expo = statistics.mean(self.exposure) if self.exposure else 0.0
        thr = float(DEFAULT_PARAMS["motion_threshold_norm"])
        flag = "" if jit < thr else "  ⚠정지판정 실패"
        return (
            f"  {self.label:<16s}"
            f"{mean_dice:5.2f}개  "
            f"{self.five_rate*100:5.0f}%  "
            f"{self.pip_rate*100:5.0f}%  "
            f"{clip*100:5.1f}%  "
            f"{conf:5.2f}  "
            f"{jit:7.5f}  "
            f"{expo:5.0f}{flag}"
        )


def _measure(
    cap: Any,
    yolo: YoloDetector,
    counter: DotCounter,
    frames: int,
    label: str,
) -> _Sample:
    s = _Sample(label)
    prev_centers: list[tuple[float, float]] = []
    tracks: dict[int, list[tuple[float, float]]] = {}

    for _ in range(frames):
        ok, frame = cap.read()
        if not ok:
            continue

        s.exposure.append(float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()))

        _tray, dice = _split(yolo.detect(frame))
        s.dice_counts.append(len(dice))

        for d in dice:
            s.confs.append(d.bbox.conf)
            s.clips.append(_clip_ratio(frame, d.bbox))
            s.pip_total += 1
            if counter.count(frame, d.bbox) is not None:
                s.pip_ok += 1

        # 정지 상태의 bbox 흔들림 — 가장 가까운 주사위끼리 이어 붙여 추적한다.
        centers = [d.bbox.center() for d in dice]
        if prev_centers:
            for c in centers:
                best, bestd = None, _MATCH_RADIUS
                for j, pc in enumerate(prev_centers):
                    dist = ((c[0] - pc[0]) ** 2 + (c[1] - pc[1]) ** 2) ** 0.5
                    if dist < bestd:
                        best, bestd = j, dist
                if best is not None:
                    tracks.setdefault(best, []).append(c)
        prev_centers = centers

    for hist in tracks.values():
        score = _motion_score(hist[-10:])
        if score != float("inf"):
            s.jitters.append(score)

    return s


async def _run(args: argparse.Namespace) -> int:
    cap = cv2.VideoCapture(args.camera)
    if not cap.isOpened():
        print(f"카메라 {args.camera}를 열 수 없다.")
        return 1
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    yolo = YoloDetector(weights_path=args.weights, conf=args.conf)
    counter = DotCounter()

    driver: LightDriver | None = None
    if not args.no_light:
        # 전구 IP는 .env에 있다. 서버는 backend/server.py가 로드해주지만 이 도구는
        # 단독 실행이라 직접 읽어야 한다 — 안 읽으면 IP가 없다며 거부한다.
        load_dotenv(Path(__file__).resolve().parent.parent / ".env")
        cfg = LightConfig.from_env()
        if cfg.driver != "yeelight" or not cfg.bulb_ips:
            print("LIGHT_DRIVER=yeelight 와 LIGHT_BULB_IP 가 필요하다. "
                  "현재 조명만 재려면 --no-light 를 쓴다.")
            cap.release()
            return 2
        driver = build_driver(cfg)
        print(f"전구 {len(cfg.bulb_ips)}개: {', '.join(cfg.bulb_ips)}")

    print("\n주사위 5개를 트레이 안에 서로 떨어뜨려 놓고, 측정 중에는 손대지 마세요.")
    print(f"설정당 {args.frames}프레임, 변경 후 {args.settle}초 대기\n")

    print("  설정            평균개수  5개검출  눈인식  과노출   신뢰도   흔들림   밝기")
    print("  " + "─" * 76)

    samples: list[_Sample] = []
    try:
        if args.no_light:
            samples.append(_measure(cap, yolo, counter, args.frames, "현재 조명"))
            print(samples[-1].row())
        else:
            assert driver is not None
            for k in _ints(args.kelvin):
                for b in _ints(args.brightness):
                    await driver.apply((255, 255, 255), b, 400, k)
                    # 카메라 자동노출이 새 밝기를 따라잡을 시간. 이걸 안 주면
                    # 직전 설정의 노출로 찍은 프레임이 섞인다.
                    time.sleep(args.settle)
                    for _ in range(5):
                        cap.read()  # 버퍼에 남은 옛 프레임 버리기
                    s = _measure(cap, yolo, counter, args.frames, f"{k}K / 밝기{b}")
                    samples.append(s)
                    print(s.row())
    finally:
        cap.release()
        if driver is not None:
            # 중립으로 되돌린다. 측정하다 만 밝기로 두고 나가지 않는다.
            from bulb.scenes import NEUTRAL_SCENE

            await driver.apply(
                NEUTRAL_SCENE.color, NEUTRAL_SCENE.brightness, 600, NEUTRAL_SCENE.kelvin
            )
            await driver.close()

    if not samples:
        return 1

    print("  " + "─" * 76)
    thr = float(DEFAULT_PARAMS["motion_threshold_norm"])
    print(f"\n  motion_threshold = {thr}  (흔들림이 이 값을 넘으면 정지 판정이 리셋된다)")

    # 5개 검출을 먼저 보고, 같으면 눈 인식으로 가른다. 둘 다 굴림 확정의 조건이다.
    best = max(samples, key=lambda s: (round(s.five_rate, 2), round(s.pip_rate, 2)))
    print(f"\n  가장 좋은 설정: {best.label}")
    print(f"    5개 검출 {best.five_rate*100:.0f}%  ·  눈 인식 {best.pip_rate*100:.0f}%")

    if best.five_rate < 0.9:
        print("\n  ⚠ 어떤 설정에서도 5개 검출이 90%에 못 미친다.")
        print("    조명만으로 해결되지 않는다. 카메라 높이·주사위 간격·트레이 배경을 함께 보라.")
    return 0


def main() -> int:
    return asyncio.run(_run(_parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
