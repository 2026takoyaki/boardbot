"""데모 6 — "진짜로 굴렸을 때만" 처리된다. 카메라 뷰만.

발표 영상용. 손으로 주사위를 가렸다 치우고, 킵존으로 옮기고, 실제로 굴리는
동작을 이어서 해도 **마지막 굴림 하나만** 처리되는 것을 카메라 화면 위에서
보여준다.

실제 요트 비전 파이프라인(YOLO + ByteTrack + RollAttributor + Fusion)을 그대로
돌린다. 판정을 흉내 내지 않는다 — 게임 서버가 내리는 것과 같은 판정이다.

화면에는 카메라와 인식 결과만 있다.
    트레이   평소 하늘색 · 손이 들어와 판정 중이면 노랑
             · 굴림 확정이면 초록 "굴림 확정 3 5 5 2 6" · 무시면 주황 "무시됨"
    굴림통   자홍
    주사위   눈 숫자 · 멈추면 초록, 움직이면 주황
    손       골격 + 플레이어 이름 (등록돼 있으면)

선행(선택): `python3 -m demos.register` — 손에 플레이어 이름을 붙이려면.

실행 (boardgame-ai 디렉터리에서):
  python3 -m demos.demo6_roll_gate --mirror
  python3 -m demos.demo6_roll_gate --mirror --record /tmp/demo6.mp4
"""

from __future__ import annotations

import cv2
import numpy as np

from bridge.local_bridge import LocalBridge
from core.constants import DEFAULT_PARAMS
from core.events import FusionContext
from demos import common
from vision.yacht.config import VisionConfig
from vision.yacht.pipeline import VisionPipeline
from vision.yacht.schemas import YachtFramePerception

# BGR
TRAY_C = (230, 200, 60)
JUDGING_C = (40, 210, 255)
CONFIRMED_C = (110, 215, 90)
IGNORED_C = (40, 150, 255)
CUP_C = (220, 90, 230)
STABLE_C = (110, 215, 90)
MOVING_C = (40, 170, 255)

# 판정 결과를 트레이에 붙여 두는 프레임 수.
RESULT_FRAMES = 60


class TextBatch:
    """한글 라벨을 모았다가 PIL로 한 번에 그린다 (프레임당 PIL 왕복 1회)."""

    def __init__(self, renderer: common.TextRenderer) -> None:
        self._r = renderer
        self._ops: list[tuple[tuple[int, int], str, tuple[int, int, int], int, str]] = []

    def add(self, pos, text, color, size, anchor="la") -> None:
        self._ops.append((pos, text, color, size, anchor))

    def flush(self, img: np.ndarray) -> None:
        if not self._ops:
            return
        if not self._r._ok:
            for (x, y), text, color, size, _a in self._ops:
                cv2.putText(img, text, (x, y + size), cv2.FONT_HERSHEY_SIMPLEX,
                            size / 32.0, color, 2, cv2.LINE_AA)
            self._ops.clear()
            return
        from PIL import Image, ImageDraw

        pil = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
        draw = ImageDraw.Draw(pil)
        for pos, text, color, size, anchor in self._ops:
            draw.text(pos, text, font=self._r._font(size),
                      fill=(color[2], color[1], color[0]), anchor=anchor)
        img[:] = cv2.cvtColor(np.array(pil), cv2.COLOR_RGB2BGR)
        self._ops.clear()


class GatePipeline(VisionPipeline):
    """요트 파이프라인을 프레임 단위로 돌려 인식 결과·판정을 돌려준다.

    VisionPipeline._process_one 과 같은 순서다(그쪽을 고치면 여기도 맞춘다).
    """

    def __init__(self, config, bridge, players, active_player: str) -> None:
        super().__init__(config, bridge, players)
        self._active = True
        self._fusion.update_context(FusionContext(
            fsm_state="AWAITING_ROLL",
            game_type="yacht",
            active_player=active_player,
            allowed_actors=[active_player],
            expected_events=["ROLL_CONFIRMED", "ROLL_UNREADABLE", "DICE_ESCAPED"],
        ))
        self._active_player = active_player
        self._has_context = True

    def step(self, frame_bgr: np.ndarray, frame_id: int, ts: float):
        h, w = frame_bgr.shape[:2]
        tray, tray_inner, roll_tray, dice_dets = self._detect_objects(frame_bgr)
        tracked = self._byte_tracker.update(dice_dets, frame_id)
        dice_states = self._dice_manager.update(tracked, frame_bgr, self._dot_counter)
        dice_states.sort(key=lambda d: d.track_id)

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        hands = self._stabilize_hands(self._hand_detector.detect(frame_rgb))

        perception = YachtFramePerception(
            frame_id=frame_id, ts=ts, image_hw=(h, w),
            tray=tray, tray_inner=tray_inner, roll_tray=roll_tray,
            dice=dice_states, hands=hands,
        )
        roll_actor = self._roll_attributor.update(perception, active_player=self._active_player)
        if roll_actor is not None:
            perception.roll_actor_id = roll_actor
        if self._roll_attributor.just_finalized:
            perception.roll_just_confirmed = True
        perception.phase_hints = {
            "dice_all_stable": perception.dice_all_stable(
                int(DEFAULT_PARAMS["stabilization_frames"])
            ),
            "dice_count": len(dice_states),
            "roll_state": self._roll_attributor.state.name,
        }

        events = self._fusion.feed(perception)
        if frame_id < self._config.warmup_frames:
            events = []
        return perception, events, self._roll_attributor.verdict, self._roll_attributor.gates()


def main() -> None:
    parser = common.base_arg_parser("진짜 굴림만 처리 — 카메라 뷰")
    parser.add_argument("--weights", default="weights/yacht_v4.pt")
    parser.add_argument("--fullscreen", action="store_true")
    args = parser.parse_args()

    players = common.load_players(args.players)
    order = [p.player_id for p in players] or ["p_1"]
    name_by_pid = {p.player_id: (p.playername or p.player_id) for p in players}
    color_by_pid = {pid: common.player_color(i) for i, pid in enumerate(order)}

    config = VisionConfig(weights_path=args.weights, warmup_frames=30)
    pipe = GatePipeline(config, LocalBridge(), players, active_player=order[0])
    tb = TextBatch(common.TextRenderer())
    demo = common.Demo("Demo6 - Roll Gate", args, show_fps=False, fullscreen=args.fullscreen)

    # 직전 판정 (라벨, 색, 남은 프레임)
    result: dict[str, object] = {"label": "", "color": TRAY_C, "ttl": 0}

    def process(frame: np.ndarray, frame_id: int, ts: float) -> np.ndarray:
        perception, events, verdict, gates = pipe.step(frame, frame_id, ts)
        stab = int(gates["stab_frames"])
        vis = frame.copy()
        h, w = vis.shape[:2]
        scale = h / 1080  # 선 두께·글자 크기를 해상도에 맞춘다
        thick = max(2, int(3 * scale))

        if verdict is not None and frame_id >= config.warmup_frames:
            if verdict.code == "confirmed":
                roll = next((e for e in events
                             if e.event_type in ("ROLL_CONFIRMED", "ROLL_UNREADABLE")), None)
                values = roll.data.get("dice_values", []) if roll and isinstance(
                    roll.data, dict) else []
                shown = " ".join(str(v) if v is not None else "?" for v in values)
                result.update(label=f"굴림 확정  {shown}".rstrip(), color=CONFIRMED_C,
                              ttl=RESULT_FRAMES)
            elif verdict.code != "rebase":
                result.update(label="무시됨", color=IGNORED_C, ttl=RESULT_FRAMES)

        def px(x: float, y: float) -> tuple[int, int]:
            return int(x * w), int(y * h)

        if perception.tray is not None:
            t = perception.tray
            if result["ttl"] > 0:
                color, label = result["color"], str(result["label"])
            elif gates["occupied"]:
                color, label = JUDGING_C, "판정 중"
            else:
                color, label = TRAY_C, "트레이"
            p1, p2 = px(t.x1, t.y1), px(t.x2, t.y2)
            cv2.rectangle(vis, p1, p2, color, thick + (2 if result["ttl"] > 0 else 0),
                          cv2.LINE_AA)
            tb.add((p1[0] + 4, max(4, p1[1] - int(40 * scale))), label, color, int(32 * scale))
        if result["ttl"] > 0:
            result["ttl"] = int(result["ttl"]) - 1

        if perception.roll_tray is not None:
            r = perception.roll_tray
            p1 = px(r.x1, r.y1)
            cv2.rectangle(vis, p1, px(r.x2, r.y2), CUP_C, thick, cv2.LINE_AA)
            tb.add((p1[0] + 4, max(4, p1[1] - int(34 * scale))), "굴림통", CUP_C,
                   int(26 * scale))

        for d in perception.dice:
            color = STABLE_C if d.stable_frames >= stab else MOVING_C
            p1, p2 = px(d.bbox.x1, d.bbox.y1), px(d.bbox.x2, d.bbox.y2)
            cv2.rectangle(vis, p1, p2, color, thick, cv2.LINE_AA)
            label = str(d.pip_count) if d.pip_count is not None else "?"
            tb.add(((p1[0] + p2[0]) // 2, p1[1] - int(8 * scale)), label, color,
                   int(34 * scale), anchor="mb")

        for hand in perception.hands:
            color = color_by_pid.get(hand.player_id, (200, 200, 200))
            pts = [px(x, y) for x, y in hand.landmarks_21]
            if len(pts) >= 21:
                for a, b in common.HAND_CONNECTIONS:
                    cv2.line(vis, pts[a], pts[b], color, thick, cv2.LINE_AA)
            for p in pts:
                cv2.circle(vis, p, thick + 1, color, -1, cv2.LINE_AA)
            if pts and hand.player_id in name_by_pid:
                tb.add((pts[0][0] + 12, pts[0][1] + 6), name_by_pid[hand.player_id], color,
                       int(28 * scale))

        tb.flush(vis)
        return vis

    try:
        demo.run(process)
    finally:
        pipe._hand_detector.close()


if __name__ == "__main__":
    main()
