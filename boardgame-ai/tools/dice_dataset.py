"""주사위 눈 인식 — 실물 사진을 모으고 정확도를 잰다.

합성 이미지로는 로직이 흔한 교란에 견디는지만 알 수 있다. 실제 카메라·조명·
주사위에서 몇 %나 맞는지는 실물 사진으로만 잴 수 있어서, 찍고 채점하는 도구를
따로 둔다.

## 1. 모으기 (카메라 필요, 백엔드는 끄고)

    python3 -m tools.dice_dataset capture
    python3 -m tools.dice_dataset capture --source 1 --out data/dice

트레이 위 주사위 **전부를 같은 눈**으로 맞춰 놓고 그 숫자 키(1~6)를 누르면
화면의 주사위가 전부 그 눈으로 저장된다. 위치·방향을 바꿔 가며 눈마다 몇 번씩
누른다(눈마다 20개 이상이면 충분하다). 화면에는 지금 로직이 읽은 값이 뜬다.

    1~6  지금 보이는 주사위를 전부 그 눈으로 저장
    u    마지막 저장 취소
    q    종료

## 2. 채점

    python3 -m tools.dice_dataset eval
    python3 -m tools.dice_dataset eval --dump /tmp/dice_wrong   # 틀린 크롭 저장
    python3 -m tools.dice_dataset eval --boxes saved            # 저장된 박스로

주사위 박스는 기본으로 사진에서 **다시 찾는다**(DiceFinder, 게임과 같은 경로).
사진마다 주사위가 몇 개인지(--expect, 기본 5) 대비 몇 개를 찾았는지와, 눈을
몇 개 맞혔는지를 방식별(hough / components / face)로 센다. 오답과 미판정을
나눠 센다 — 미판정은 다수결 버퍼가 흡수하지만 오답은 표를 갉아먹는다.

저장 형식: <out>/frames/*.jpg (원본 프레임) + <out>/labels.jsonl
(프레임마다 {"frame", "dice": [{"bbox": [x1,y1,x2,y2], "label": n}]}).
원본 프레임과 bbox를 남기므로 크롭 방식을 바꿔도 다시 찍을 필요가 없다.
"""

from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from pathlib import Path

import cv2

from vision.detectors.dot_counter import DotCounter, DotCounterParams
from vision.schemas import BBox

DEFAULT_OUT = Path("data/dice")


def _load(out: Path) -> list[dict]:
    path = out / "labels.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _save_all(out: Path, rows: list[dict]) -> None:
    (out / "labels.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def capture(args: argparse.Namespace) -> None:
    from vision.detectors.yolo_detector import YoloDetector

    out = Path(args.out)
    (out / "frames").mkdir(parents=True, exist_ok=True)
    rows = _load(out)
    from vision.detectors.dice_finder import DiceFinder

    yolo = YoloDetector(args.weights)
    finder = DiceFinder()
    counter = DotCounter()

    src: int | str = int(args.source) if str(args.source).isdigit() else args.source
    cap = cv2.VideoCapture(src)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, args.width)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, args.height)
    if not cap.isOpened():
        print(f"카메라 열기 실패: {src} (백엔드가 카메라를 쓰고 있으면 끄고 다시)")
        return

    flash = ("", 0)
    print("주사위를 전부 같은 눈으로 맞추고 숫자 키(1~6). u 취소, q 종료.")
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if args.mirror:
                frame = cv2.flip(frame, 1)
            dets = yolo.detect(frame)
            if args.boxes == "yolo":
                dice = [d.bbox for d in dets if d.cls_name == "dice"]
            else:
                trays = [d.bbox for d in dets if d.cls_name in ("tray", "tray_inner")]
                dice = [d.bbox for d in finder.find(frame, trays)]
            vis = frame.copy()
            h, w = vis.shape[:2]
            for b in dice:
                got = counter.count(frame, b)
                p1, p2 = (int(b.x1 * w), int(b.y1 * h)), (int(b.x2 * w), int(b.y2 * h))
                color = (90, 215, 110) if got is not None else (40, 170, 255)
                cv2.rectangle(vis, p1, p2, color, 2)
                cv2.putText(vis, str(got) if got is not None else "?", (p1[0], p1[1] - 6),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2, cv2.LINE_AA)
            counts = Counter(d["label"] for r in rows for d in r["dice"])
            summary = "  ".join(f"{n}:{counts.get(n, 0)}" for n in range(1, 7))
            cv2.putText(vis, f"saved  {summary}", (16, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
                        (255, 255, 255), 2, cv2.LINE_AA)
            if flash[1] > 0:
                cv2.putText(vis, flash[0], (16, 76), cv2.FONT_HERSHEY_SIMPLEX, 1.0,
                            (90, 215, 110), 2, cv2.LINE_AA)
                flash = (flash[0], flash[1] - 1)
            cv2.imshow("dice dataset", vis)

            key = cv2.waitKey(1) & 0xFF
            if key in (ord("q"), 27):
                break
            if ord("1") <= key <= ord("6") and dice:
                label = key - ord("0")
                name = f"{time.strftime('%Y%m%d_%H%M%S')}_{int(time.time() * 1000) % 1000:03d}.jpg"
                cv2.imwrite(str(out / "frames" / name), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                rows.append({
                    "frame": name,
                    "dice": [{"bbox": [b.x1, b.y1, b.x2, b.y2], "label": label} for b in dice],
                })
                _save_all(out, rows)
                flash = (f"{len(dice)} dice -> {label}", 30)
            elif key == ord("u") and rows:
                last = rows.pop()
                (out / "frames" / last["frame"]).unlink(missing_ok=True)
                _save_all(out, rows)
                flash = ("undo", 30)
    finally:
        cap.release()
        cv2.destroyAllWindows()
    print(f"저장: {out}  (프레임 {len(rows)}개)")


def evaluate(args: argparse.Namespace) -> None:
    out = Path(args.out)
    rows = _load(out)
    if not rows:
        print(f"사진이 없다: {out}/labels.jsonl — 먼저 capture")
        return
    dump = Path(args.dump) if args.dump else None
    if dump:
        dump.mkdir(parents=True, exist_ok=True)

    methods = {
        "hough": DotCounter(DotCounterParams(method="hough")),
        "components": DotCounter(DotCounterParams(method="components")),
        "face": DotCounter(DotCounterParams(method="face")),
    }
    boxes_by_frame: dict[str, list[tuple[BBox, int]]] = {}
    if args.boxes == "finder":
        from vision.detectors.dice_finder import DiceFinder
        from vision.detectors.yolo_detector import YoloDetector

        yolo = YoloDetector(args.weights)
        found_total = 0
        for row in rows:
            frame = cv2.imread(str(out / "frames" / row["frame"]))
            if frame is None:
                continue
            label = int(row["dice"][0]["label"])  # 사진 한 장 = 같은 눈
            dets = yolo.detect(frame)
            trays = [d.bbox for d in dets if d.cls_name in ("tray", "tray_inner")]
            found = [d.bbox for d in DiceFinder().find(frame, trays)]
            found_total += len(found)
            boxes_by_frame[row["frame"]] = [(b, label) for b in found]
        print(f"검출: 사진 {len(rows)}장 × {args.expect}개 = {len(rows) * args.expect}개 중 "
              f"{found_total}개 찾음 (DiceFinder)\n")
    else:
        for row in rows:
            boxes_by_frame[row["frame"]] = [
                (BBox(*d["bbox"], 0.9, "dice"), int(d["label"])) for d in row["dice"]
            ]
    for name, counter in methods.items():
        right = none = 0
        total = 0
        per_face: Counter[int] = Counter()
        per_face_right: Counter[int] = Counter()
        confusion: Counter[tuple[int, int]] = Counter()
        for row in rows:
            frame = cv2.imread(str(out / "frames" / row["frame"]))
            if frame is None:
                continue
            for i, (bbox, label) in enumerate(boxes_by_frame.get(row["frame"], [])):
                got = counter.count(frame, bbox)
                total += 1
                per_face[label] += 1
                if got == label:
                    right += 1
                    per_face_right[label] += 1
                elif got is None:
                    none += 1
                else:
                    confusion[(label, got)] += 1
                if dump and name == "components" and got != label:
                    h, w = frame.shape[:2]
                    x1, y1 = int(bbox.x1 * w), int(bbox.y1 * h)
                    x2, y2 = int(bbox.x2 * w), int(bbox.y2 * h)
                    crop = frame[max(0, y1):y2, max(0, x1):x2]
                    tag = "none" if got is None else str(got)
                    cv2.imwrite(str(dump / f"{label}_as_{tag}_{row['frame'][:-4]}_{i}.png"), crop)
        if total == 0:
            continue
        wrong = total - right - none
        faces = "  ".join(
            f"{f}:{per_face_right[f]}/{per_face[f]}" for f in range(1, 7) if per_face[f]
        )
        print(f"{name:11s} 정답 {right / total:6.1%}  미판정 {none / total:6.1%}  "
              f"오답 {wrong / total:6.1%}  (주사위 {total}개)")
        print(f"{'':11s} 눈별 {faces}")
        if confusion:
            common = ", ".join(f"{a}→{b} {n}회" for (a, b), n in confusion.most_common(5))
            print(f"{'':11s} 잦은 오답 {common}")
    if dump:
        print(f"틀린 크롭: {dump}  (파일명 = 정답_as_읽은값)")


def main() -> None:
    parser = argparse.ArgumentParser(description="주사위 눈 인식 데이터 수집·채점")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("capture")
    c.add_argument("--source", default="0")
    c.add_argument("--width", type=int, default=1920)
    c.add_argument("--height", type=int, default=1080)
    c.add_argument("--mirror", action="store_true")
    c.add_argument("--weights", default="weights/yacht_v4.pt")
    c.add_argument("--out", default=str(DEFAULT_OUT))
    c.add_argument("--boxes", choices=("finder", "yolo"), default="finder")
    e = sub.add_parser("eval")
    e.add_argument("--out", default=str(DEFAULT_OUT))
    e.add_argument("--dump", default=None)
    e.add_argument("--boxes", choices=("finder", "saved"), default="finder")
    e.add_argument("--expect", type=int, default=5, help="사진마다 주사위 수")
    e.add_argument("--weights", default="weights/yacht_v4.pt")
    args = parser.parse_args()
    if args.cmd == "capture":
        capture(args)
    else:
        evaluate(args)


if __name__ == "__main__":
    main()
