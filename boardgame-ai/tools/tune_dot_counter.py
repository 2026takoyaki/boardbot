"""주사위 눈 수 파라미터 실시간 튜닝 도구.

트랙바로 HoughCircles/Blob 파라미터와 **조명**을 함께 조절하면서
실제 카메라 또는 저장된 영상에서 인식 결과를 실시간 확인.

조명을 같이 넣은 이유: 눈 인식 파라미터의 최적값은 조도에 따라 달라진다.
따로 맞추면 조명을 바꾸는 순간 파라미터가 어긋나므로, 같은 화면에서 함께
움직여야 한다.

Usage:
    python3 -m tools.tune_dot_counter
    python3 -m tools.tune_dot_counter --source /tmp/session.mp4
    python3 -m tools.tune_dot_counter --no-light    # 전구 없이 파라미터만

조작:
    트랙바     : 각 파라미터 · 밝기 · 색온도 조절
    's'        : 현재 파라미터와 조명값 출력 (복사해서 코드에 붙여넣기)
    'q'        : 종료 (조명은 중립으로 되돌린다)

전구는 .env 의 LIGHT_DRIVER / LIGHT_BULB_IP 를 읽는다. 설정이 없으면 조명
트랙바 없이 파라미터 튜닝만 동작한다.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import threading
import time
from collections import Counter, deque
from pathlib import Path

import cv2
import numpy as np
from dotenv import load_dotenv

from bulb import LightConfig, build_driver
from bulb.driver.base import KELVIN_MAX, KELVIN_MIN, LightDriver
from vision.detectors.dot_counter import DotCounter, DotCounterParams
from vision.detectors.yolo_detector import YoloDetector

# 색온도 트랙바는 100K 단위로 움직인다. 1K 단위는 트랙바로 다룰 수 없고
# 눈으로도 구분되지 않는다.
_KELVIN_STEP = 100
_KELVIN_SLOTS = (KELVIN_MAX - KELVIN_MIN) // _KELVIN_STEP  # 48

_WHITE = (255, 255, 255)


class _LightControl:
    """트랙바 값을 전구에 반영한다. 마지막 값만 일정 간격으로 보낸다.

    Yeelight는 분당 명령 수 제한이 있는데, 트랙바는 드래그 한 번에 수십 개의
    값을 낸다. 그대로 보내면 전구가 명령을 거부하기 시작하고 그때부터 조절이
    먹지 않는다. 그래서 목표값만 갱신해두고 백그라운드에서 간격을 두고 보낸다.

    별도 스레드에서 도는 이유는 cv2 루프가 동기이기 때문이다. 여기서 전구
    응답을 기다리면 화면이 멈춘다.
    """

    def __init__(self, driver: LightDriver, min_interval: float = 0.4) -> None:
        self._driver = driver
        self._min_interval = min_interval
        self._target: tuple[int, int] | None = None
        self._sent: tuple[int, int] | None = None
        self._error: str | None = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True, name="light-tune")
        self._thread.start()

    def set(self, brightness: int, kelvin: int) -> None:
        with self._lock:
            self._target = (brightness, kelvin)

    @property
    def error(self) -> str | None:
        with self._lock:
            return self._error

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            while not self._stop.is_set():
                with self._lock:
                    target = self._target
                if target is not None and target != self._sent:
                    self._sent = target
                    brightness, kelvin = target
                    try:
                        loop.run_until_complete(
                            self._driver.apply(_WHITE, brightness, 300, kelvin)
                        )
                        with self._lock:
                            self._error = None
                    except Exception as exc:  # 전구가 죽어도 튜닝은 계속돼야 한다
                        with self._lock:
                            self._error = str(exc)[:60]
                self._stop.wait(self._min_interval)
        finally:
            loop.close()

    def close(self) -> None:
        """중립으로 되돌리고 정리한다. 튜닝하다 만 밝기로 두고 나가지 않는다."""
        self._stop.set()
        self._thread.join(timeout=2.0)
        from bulb.scenes import NEUTRAL_SCENE

        async def _restore() -> None:
            await self._driver.apply(
                NEUTRAL_SCENE.color, NEUTRAL_SCENE.brightness, 600, NEUTRAL_SCENE.kelvin
            )
            await self._driver.close()

        # 되돌리기 실패가 종료를 막을 이유는 없다.
        with contextlib.suppress(Exception):
            asyncio.run(_restore())


class _PipVoter:
    """파이프라인이 실제로 보는 값을 재현한다.

    DotCounter의 프레임별 원본 출력은 원래 흔들린다. 파이프라인은 그걸 그대로
    쓰지 않고 DiceManager가 버퍼에 모아 다수결로 확정한다. 원본만 띄우면
    "깜빡거린다"까지는 보이지만 그게 굴림 확정으로 이어지는지는 알 수 없다.

    채택 조건은 DiceManager와 같다 — 1위 표수 >= max(3, 버퍼/3) 이고
    2위보다 2표 이상 앞설 것. 두 값이 비등하면 확정하지 않는다.

    주사위를 프레임 간에 잇는 방법은 가장 가까운 중심이다. 튜닝 중에는 주사위가
    가만히 있으므로 ByteTracker까지 돌릴 이유가 없다.
    """

    def __init__(self, buffer_size: int = 11, match_radius: float = 0.05) -> None:
        self._buffer_size = buffer_size
        self._match_radius = match_radius
        self._slots: list[dict] = []  # {"center", "buf", "voted", "miss"}

    def update(self, readings: list[tuple[tuple[float, float], int | None]]) -> list[dict]:
        """(중심, 원본_pip) 목록을 받아 슬롯별 상태를 돌려준다."""
        used: set[int] = set()
        result: list[dict] = []

        for center, raw in readings:
            slot = None
            best = self._match_radius
            for i, s in enumerate(self._slots):
                if i in used:
                    continue
                d = ((center[0] - s["center"][0]) ** 2 + (center[1] - s["center"][1]) ** 2) ** 0.5
                if d < best:
                    slot, best = i, d
            if slot is None:
                self._slots.append(
                    {"center": center, "buf": deque(maxlen=self._buffer_size), "voted": None}
                )
                slot = len(self._slots) - 1
            used.add(slot)

            s = self._slots[slot]
            s["center"] = center
            if raw is not None:
                s["buf"].append(raw)
                top = Counter(s["buf"]).most_common(2)
                if top:
                    candidate, votes = top[0]
                    runner_up = top[1][1] if len(top) > 1 else 0
                    min_votes = max(3, len(s["buf"]) // 3)
                    if votes >= min_votes and (votes - runner_up) >= 2:
                        s["voted"] = candidate

            buf = list(s["buf"])
            agree = buf.count(s["voted"]) / len(buf) if buf and s["voted"] is not None else 0.0
            result.append({"raw": raw, "voted": s["voted"], "agree": agree, "buf": buf})

        # 오래 안 잡힌 슬롯은 버린다 — 주사위를 옮기면 옛 자리가 남는다.
        self._slots = [s for i, s in enumerate(self._slots) if i in used]
        return result

    def reset(self) -> None:
        self._slots.clear()


def _build_light(enabled: bool) -> tuple[_LightControl | None, str]:
    """조명 조절기를 만든다. 못 만들면 이유를 함께 돌려준다."""
    if not enabled:
        return None, "조명 조절 꺼짐 (--no-light)"
    load_dotenv(Path(__file__).resolve().parent.parent / ".env")
    cfg = LightConfig.from_env()
    if cfg.driver != "yeelight" or not cfg.bulb_ips:
        return None, "전구 설정 없음 (.env 의 LIGHT_DRIVER / LIGHT_BULB_IP 확인)"
    try:
        return _LightControl(build_driver(cfg)), f"전구 {len(cfg.bulb_ips)}개 연결"
    except Exception as exc:
        return None, f"전구 연결 실패: {exc}"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="주사위 눈 인식 파라미터 + 조명 실시간 튜닝")
    p.add_argument("--source", default="0", help="카메라 인덱스 또는 영상 경로")
    p.add_argument("--weights", default="weights/yacht_v4.pt")
    p.add_argument("--conf", type=float, default=0.35, help="YOLO 신뢰도 임계값")
    p.add_argument("--no-light", action="store_true", help="전구를 건드리지 않는다")
    p.add_argument("--brightness", type=int, default=70, help="시작 밝기")
    p.add_argument("--kelvin", type=int, default=4000, help="시작 색온도")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    try:
        source: int | str = int(args.source)
    except ValueError:
        source = args.source

    light, light_status = _build_light(not args.no_light)
    print(f"[tune] {light_status}")

    yolo = YoloDetector(args.weights, conf=args.conf, iou=0.5, imgsz=640)
    params = DotCounterParams()
    counter = DotCounter(params)

    WIN = "tune_dot_counter"
    cv2.namedWindow(WIN, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WIN, 1440, 810)

    def _tb(name: str, val: int, maxv: int) -> None:
        cv2.createTrackbar(name, WIN, val, maxv, lambda _: None)

    # 조명을 맨 위에 둔다. 조도를 먼저 정하고 그 아래서 파라미터를 맞추는 순서다.
    if light is not None:
        start_slot = max(0, min(_KELVIN_SLOTS, (args.kelvin - KELVIN_MIN) // _KELVIN_STEP))
        _tb("* light bright", max(1, min(100, args.brightness)), 100)
        _tb("* light kelvin", start_slot, _KELVIN_SLOTS)

    _tb("dp x10", int(params.dp * 10), 30)
    _tb("min_dist%", int(params.min_dist_ratio * 100), 80)
    _tb("canny_upper", params.canny_upper, 200)
    _tb("accum_thresh", params.accum_thresh, 50)
    _tb("r_min%", int(params.radius_min_ratio * 100), 20)
    _tb("r_max%", int(params.radius_max_ratio * 100), 40)
    _tb("clahe_clip x10", int(params.clahe_clip * 10), 80)
    _tb("stable_frames", 15, 60)

    cap = cv2.VideoCapture(source)
    if not cap.isOpened():
        print(f"[tune] 소스 {source}를 열 수 없다. 백엔드 서버가 카메라를 잡고 있는지 확인하라.")
        if light is not None:
            light.close()
        return

    print("[tune] 's' 파라미터 출력   'r' 투표 초기화   'q' 종료")

    voter = _PipVoter()
    brightness, kelvin = args.brightness, args.kelvin
    last_light_push = 0.0

    while True:
        ret, frame = cap.read()
        if not ret:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            continue

        params.dp = max(0.1, cv2.getTrackbarPos("dp x10", WIN) / 10)
        params.min_dist_ratio = max(0.01, cv2.getTrackbarPos("min_dist%", WIN) / 100)
        params.canny_upper = max(1, cv2.getTrackbarPos("canny_upper", WIN))
        params.accum_thresh = max(1, cv2.getTrackbarPos("accum_thresh", WIN))
        params.radius_min_ratio = max(0.01, cv2.getTrackbarPos("r_min%", WIN) / 100)
        params.radius_max_ratio = max(0.02, cv2.getTrackbarPos("r_max%", WIN) / 100)
        params.clahe_clip = max(0.1, cv2.getTrackbarPos("clahe_clip x10", WIN) / 10)
        stable_frames = cv2.getTrackbarPos("stable_frames", WIN)

        if light is not None:
            brightness = max(1, cv2.getTrackbarPos("* light bright", WIN))
            kelvin = KELVIN_MIN + cv2.getTrackbarPos("* light kelvin", WIN) * _KELVIN_STEP
            # 화면 루프는 30fps다. 매 프레임 밀어 넣으면 조절기의 큐가 의미를 잃는다.
            now = time.monotonic()
            if now - last_light_push >= 0.1:
                light.set(brightness, kelvin)
                last_light_push = now

        dets = yolo.detect(frame)
        dice_dets = [d for d in dets if d.cls_name == "dice"]

        h, w = frame.shape[:2]
        vis = frame.copy()

        crops: list[np.ndarray] = []
        readings: list[tuple[tuple[float, float], int | None]] = []
        for det in dice_dets:
            result, crop_vis = counter.count_with_debug(frame, det.bbox)
            crops.append(cv2.resize(crop_vis, (120, 120)))
            readings.append((det.bbox.center(), result))

        votes = voter.update(readings)
        read_ok = sum(1 for v in votes if v["raw"] is not None)
        settled = sum(1 for v in votes if v["voted"] is not None)

        for det, v in zip(dice_dets, votes, strict=True):
            x1 = int(det.bbox.x1 * w)
            y1 = int(det.bbox.y1 * h)
            x2 = int(det.bbox.x2 * w)
            y2 = int(det.bbox.y2 * h)
            # 테두리는 **확정값** 기준이다. 원본이 깜빡여도 확정이 서 있으면
            # 파이프라인은 그 값을 쓴다 — 그게 판단해야 할 상태다.
            color = (0, 255, 0) if v["voted"] is not None else (0, 0, 255)
            cv2.rectangle(vis, (x1, y1), (x2, y2), color, 2)

            raw = str(v["raw"]) if v["raw"] is not None else "?"
            voted = str(v["voted"]) if v["voted"] is not None else "-"
            cv2.putText(
                vis, voted, (x1, y1 - 8), cv2.FONT_HERSHEY_SIMPLEX, 1.0, color, 2
            )
            # 원본과 일치율을 작게 곁들인다. 일치율이 낮으면 확정이 서 있어도
            # 언제든 흔들릴 수 있다는 뜻이다.
            cv2.putText(
                vis,
                f"raw {raw}  {v['agree']*100:.0f}%",
                (x1, y2 + 18),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (200, 200, 200),
                1,
            )

        # 굴림이 확정되려면 5개가 다 잡히고 5개가 다 **확정**돼야 한다.
        # read는 이번 프레임에 읽힌 개수, settled는 다수결이 선 개수다.
        # 둘의 차이가 곧 깜빡임의 크기다.
        ok = len(dice_dets) == 5 and settled == 5
        cv2.putText(
            vis,
            f"dice {len(dice_dets)}/5   read {read_ok}/5   settled {settled}/5",
            (10, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1.1,
            (0, 255, 0) if ok else (0, 165, 255),
            2,
        )

        info = (
            f"dp={params.dp:.1f} dist={params.min_dist_ratio:.2f} "
            f"canny={params.canny_upper} acc={params.accum_thresh} "
            f"r={params.radius_min_ratio:.2f}-{params.radius_max_ratio:.2f} "
            f"clahe={params.clahe_clip:.1f} stable={stable_frames}f"
        )
        cv2.putText(vis, info, (10, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 0), 1)

        if light is not None:
            err = light.error
            light_line = f"LIGHT  {kelvin}K  bright {brightness}" + (f"   [{err}]" if err else "")
            cv2.putText(
                vis,
                light_line,
                (10, 96),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (0, 0, 255) if err else (200, 200, 255),
                2,
            )
        else:
            cv2.putText(
                vis, light_status, (10, 96), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 150), 1
            )

        if crops:
            tile_col = np.vstack(crops[:6])
            pad_h = max(0, vis.shape[0] - tile_col.shape[0])
            if pad_h > 0:
                tile_col = np.vstack([tile_col, np.zeros((pad_h, 120, 3), dtype=np.uint8)])
            else:
                tile_col = tile_col[: vis.shape[0]]
            vis = np.hstack([vis, tile_col])

        cv2.imshow(WIN, vis)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        if key == ord("r"):
            # 파라미터를 바꾸면 이전 값으로 쌓인 표가 남아 판단을 흐린다.
            voter.reset()
            print("[tune] 투표 버퍼 초기화")
        if key == ord("s"):
            print("\n=== DotCounterParams (vision/detectors/dot_counter.py) ===")
            print("DotCounterParams(")
            print(f"    dp={params.dp},")
            print(f"    min_dist_ratio={params.min_dist_ratio},")
            print(f"    canny_upper={params.canny_upper},")
            print(f"    accum_thresh={params.accum_thresh},")
            print(f"    radius_min_ratio={params.radius_min_ratio},")
            print(f"    radius_max_ratio={params.radius_max_ratio},")
            print(f"    clahe_clip={params.clahe_clip},")
            print(")")
            print(f"stable_frames = {stable_frames}")
            if light is not None:
                print("\n=== 조명 (bulb/scenes.py) ===")
                print(f"NEUTRAL_KELVIN = {kelvin}")
                print(f"NEUTRAL_SCENE brightness = {brightness}")
            print("==========================================================\n")

    cap.release()
    cv2.destroyAllWindows()
    if light is not None:
        light.close()


if __name__ == "__main__":
    main()
