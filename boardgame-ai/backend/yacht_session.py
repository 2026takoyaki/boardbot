"""YachtFSM을 WebSocket 클라이언트 방식으로 구동하는 세션."""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from copy import deepcopy
from typing import Any

from fastapi import WebSocket

from agents import lines
from agents.context import AgentContext
from agents.orchestrator import AgentOrchestrator
from audio.manager import AudioManager
from backend.dev import is_dev_mode
from bridge.local_bridge import LocalBridge
from bulb.controller import LightController
from core.constants import MsgType
from core.envelope import WSMessage
from core.events import FusionContext, GameEvent
from games.yacht import YachtEventType, YachtFSM, YachtGameState, YachtInputType, YachtPhase

# AudioManager가 가로채는 msg_type 집합. session.send()에서 분기 기준.
_AUDIO_MSG_TYPES = {
    MsgType.TTS_PLAY.value,
    MsgType.TTS_INTERRUPT.value,
    MsgType.SFX_PLAY.value,
    MsgType.BGM_PLAY.value,
    MsgType.BGM_DUCK.value,
}


class YachtSession:
    def __init__(
        self,
        websocket: WebSocket,
        pipeline_switcher: Callable[[str | None], None] | None = None,
        bridge: LocalBridge | None = None,
        audio_manager: AudioManager | None = None,
        agent_orchestrator: AgentOrchestrator | None = None,
        light_controller: LightController | None = None,
    ) -> None:
        self.websocket = websocket
        self.fsm: YachtFSM | None = None
        self.tutorial_mode = False
        self.tutorial_complete = False
        self.undo_stack: list[YachtGameState] = []
        self._pipeline_switcher = pipeline_switcher
        self._bridge = bridge
        self._audio_manager = audio_manager
        self._agent = agent_orchestrator
        self._light = light_controller
        self._last_tts_request: tuple[str, float] = ("", 0.0)
        self._send_raw_bound = self._send_raw
        if audio_manager is not None:
            audio_manager.attach_broadcast(
                self._send_raw_bound, session_id=audio_manager.get_session_id()
            )
        # FSM 상태 변경 직렬화 — 비전 스레드와 WS 스레드가 동시에 호출 가능
        self._fsm_lock = threading.Lock()

    async def _speak(self, text: str | None, interrupt_existing: bool = False) -> None:
        """프론트가 요청한 발화. 같은 문장이 연달아 오면 한 번만 읽는다.

        튜토리얼 화면이 리렌더될 때마다 같은 안내를 다시 보내는 경로가 있어,
        중복 억제가 없으면 같은 말을 두세 번 반복한다.
        """
        if not text or self._audio_manager is None:
            return
        if interrupt_existing:
            await self._audio_manager.interrupt_interruptible("tutorial_step_changed")
        now = time.monotonic()
        last_text, last_at = self._last_tts_request
        if text == last_text and now - last_at < 4.0:
            return
        self._last_tts_request = (text, now)
        state_version = self.fsm.state.state_version if self.fsm is not None else 0
        await self._audio_manager.enqueue_tts(text=text, state_version=state_version)

    async def send_hello(self) -> None:
        # 멘트 카탈로그를 접속 시 통째로 준다. 프론트도 같은 문장을 화면에 그려야
        # 하는데(튜토리얼 인트로 등) 발화마다 왕복하면 타이밍이 흔들린다.
        await self.send(
            WSMessage.make_hello({"game_type": "yacht", "lines": lines.catalog()})
        )

    async def dispatch_vision_event(self, event: GameEvent) -> None:
        """yacht_runner가 호출. 비전 이벤트를 FSM에 전달하고 응답을 클라이언트로."""
        if self.fsm is None or self.tutorial_complete:
            return
        if self._agent is not None:
            await self._agent.on_game_event(event)
        with self._fsm_lock:
            # 비전이 발화한 ROLL_CONFIRMED도 수동 ROLL_DICE 입력과 동일하게
            # undo 히스토리에 push해야 사용자가 비전 인식이 틀린 경우 되돌릴 수 있다.
            previous_state = (
                deepcopy(self.fsm.state)
                if event.event_type == YachtEventType.ROLL_CONFIRMED.value
                else None
            )
            messages = self.fsm.handle_event(event)
            if (
                previous_state is not None
                and self._roll_was_recorded(previous_state)
            ):
                self.undo_stack.append(previous_state)
            self._apply_tutorial_message_override(messages)
        await self.send_many(messages)

    async def handle_client_message(self, data: dict[str, Any]) -> None:
        input_type = str(data.get("input_type", ""))
        payload = dict(data.get("data", {}))
        player_id = data.get("player_id")

        # frontend가 오디오 재생 끝/중단을 통보. AudioManager 큐 진행 트리거.
        if input_type == "audio_ack" and self._audio_manager is not None:
            pbid = str(payload.get("playback_id", ""))
            status = str(payload.get("status", ""))
            if pbid:
                await self._audio_manager.handle_ack(pbid, status)
            return

        if input_type == "SET_STRATEGY_COACHING":
            if self._agent is not None:
                self._agent.set_strategy_enabled(bool(payload.get("enabled", False)))
            return

        if input_type == "NARRATION_REQUEST":
            # 프론트가 문장이 아니라 line_id를 보낸다. 문장은 백엔드가 소유하므로
            # 페르소나를 바꾸면 프론트를 건드리지 않아도 말투가 바뀐다.
            await self._speak(
                lines.render(
                    str(payload.get("line_id", "")), **dict(payload.get("params") or {})
                ),
                interrupt_existing=bool(payload.get("interrupt_existing")),
            )
            return

        if input_type == "TTS_REQUEST":
            await self._speak(
                str(payload.get("text") or "").strip(),
                interrupt_existing=bool(payload.get("interrupt_existing")),
            )
            return

        if input_type == "BGM_SET":
            if self._audio_manager is not None:
                if bool(payload.get("enabled", True)):
                    await self._audio_manager.play_bgm("yacht_walk", gain_db=-12.0)
                else:
                    await self._audio_manager.pause_bgm()
            return

        if input_type == "BGM_STOP":
            if self._audio_manager is not None:
                await self._audio_manager.stop_bgm()
            return

        # frontend bench hook → backend bench_log로 통합.
        if input_type == "bench_trace":
            from benchmarks.relay import handle_bench_trace
            handle_bench_trace(payload)
            return

        if input_type == "START_YACHT":
            # Benchmark hook: 게임 시작 시각 (completion_rate 측정용).
            try:
                import time as _t

                from benchmarks.common.trace_setup import bench_log
                bench_log().info("game_start yacht %.6f", _t.time())
            except Exception:
                pass
            await self.start_game(payload)
            return

        if self.fsm is None:
            await self.send(
                WSMessage.make_error("GAME_NOT_STARTED", "요트다이스가 시작되지 않았습니다.")
            )
            return

        # 개발 모드 전용. 역전 연출은 7칸 이상 채워야 나오는데 손으로 채우려면
        # 20턴 넘게 굴려야 한다. 연출 하나 보려고 매번 그럴 수는 없다.
        if input_type == "DEV_SETUP_LATE_GAME":
            if not is_dev_mode():
                return
            with self._fsm_lock:
                self._dev_setup_late_game()
                messages = self.fsm._state_context_messages()
            await self.send_many(messages)
            return

        if input_type == "ROLL_DICE":
            with self._fsm_lock:
                previous_state = deepcopy(self.fsm.state)
                dice_values = payload.get("dice_values") or self._roll_dice(
                    self.fsm.state.dice_values,
                    self.fsm.state.keep_mask,
                )
                event = GameEvent(
                    event_type=YachtEventType.ROLL_CONFIRMED.value,
                    actor_id=self.fsm.state.current_player.player_id,
                    confidence=1.0,
                    frame_id=-1,
                    data={"dice_values": dice_values, "keep_mask": self.fsm.state.keep_mask},
                )
                messages = self.fsm.handle_event(event)
                if self._roll_was_recorded(previous_state):
                    self.undo_stack.append(previous_state)
                    # Benchmark hook: 실제로 카운트된 굴림 (undo_rate 분모).
                    try:
                        from benchmarks.common.trace_setup import bench_log
                        bench_log().info("roll_confirmed -")
                    except Exception:
                        pass
                self._apply_tutorial_message_override(messages)
            await self.send_many(messages)
            return

        if input_type == "MANUAL_DICE_INPUT":
            dice_values = payload.get("dice_values")
            if not self._is_valid_manual_dice(dice_values):
                await self.send(
                    WSMessage.make_error(
                        "INVALID_DICE_VALUES",
                        "주사위 값은 1부터 6까지 5개를 입력해야 합니다.",
                        self.fsm.state.state_version,
                    )
                )
                return

            # Benchmark hook: 사용자의 눈 수 직접 정정 = 순수 인식 실패 신호
            # (undo_round와 함께 인식 정확도 proxy로 집계).
            try:
                from benchmarks.common.trace_setup import bench_log
                bench_log().info("manual_dice_correction -")
            except Exception:
                pass

            with self._fsm_lock:
                previous_state = deepcopy(self.fsm.state)
                if self.fsm.state.unreadable_roll is not None:
                    # 인식 실패로 점수 단계(AWAITING_SCORE)에 강제 진입한 굴림을
                    # 수동 입력으로 확정한다. 단순히 눈만 덮어쓰면 굴림이 카운트되지
                    # 않은 채 AWAITING_SCORE에 머물러 (1) 남은 굴림 기회가 사라지고
                    # (2) 비전이 ROLL_CONFIRMED를 거부하는 단계라 다시 굴려도 인식이
                    # 안 된다. 정식 해소 경로로 보내 이 굴림을 1회로 카운트하고
                    # AWAITING_KEEP으로 복귀시켜 남은 굴림 기회를 보존한다.
                    messages = self.fsm._handle_unreadable_resolution(
                        {"dice_values": [int(v) for v in dice_values]}
                    )
                    if self._roll_was_recorded(previous_state):
                        self.undo_stack.append(previous_state)
                elif self.fsm.state.phase in (
                    YachtPhase.AWAITING_KEEP.value,
                    YachtPhase.AWAITING_SCORE.value,
                ):
                    sorted_values, sorted_keep_mask = self.fsm._sort_dice_with_keep(
                        [int(v) for v in dice_values],
                        self.fsm.state.keep_mask,
                    )
                    self.fsm.state.dice_values = sorted_values
                    self.fsm.state.keep_mask = sorted_keep_mask
                    self.fsm.state.unreadable_roll = None
                    self.fsm.narrate_roll()
                    self.fsm.state.state_version += 1
                    messages = self.fsm._state_context_messages()
                    self.undo_stack.append(previous_state)
                else:
                    event = GameEvent(
                        event_type=YachtEventType.ROLL_CONFIRMED.value,
                        actor_id=self.fsm.state.current_player.player_id,
                        confidence=1.0,
                        frame_id=-1,
                        data={"dice_values": dice_values, "keep_mask": self.fsm.state.keep_mask},
                    )
                    messages = self.fsm.handle_event(event)
                    if self._roll_was_recorded(previous_state):
                        self.undo_stack.append(previous_state)
                self._apply_tutorial_message_override(messages)
            await self.send_many(messages)
            return

        if input_type == "DICE_ESCAPED":
            event = GameEvent(
                event_type=YachtEventType.DICE_ESCAPED.value,
                actor_id=self.fsm.state.current_player.player_id,
                confidence=1.0,
                frame_id=-1,
                data={},
            )
            with self._fsm_lock:
                messages = self.fsm.handle_event(event)
            await self.send_many(messages)
            return

        if input_type in {
            YachtInputType.DICE_KEEP_SELECTED.value,
            YachtInputType.DICE_REROLL_REQUESTED.value,
            YachtInputType.RESOLVE_UNREADABLE_ROLL.value,
        }:
            with self._fsm_lock:
                messages = self.fsm.handle_input(input_type, payload, player_id)
                self._apply_tutorial_message_override(messages)
            await self.send_many(messages)
            if self._audio_manager is not None and (
                self.tutorial_complete or self.fsm.state.phase == YachtPhase.GAME_END.value
            ):
                await self._audio_manager.stop_bgm()
            return

        if input_type == YachtInputType.SCORE_CATEGORY_SELECTED.value:
            with self._fsm_lock:
                previous_state = deepcopy(self.fsm.state)
                messages = self.fsm.handle_input(input_type, payload, player_id)
                if self._score_was_recorded(previous_state, payload.get("category")):
                    self.undo_stack = []
                    self._finish_tutorial_if_complete(messages)
                self._apply_tutorial_message_override(messages)
            await self.send_many(messages)
            return

        if input_type == "UNDO_ROUND":
            # Benchmark hook: 인식 신뢰도 proxy (undo_rate 측정용).
            try:
                from benchmarks.common.trace_setup import bench_log
                bench_log().info("undo_round -")
            except Exception:
                pass
            if not self.undo_stack:
                await self.send(
                    WSMessage.make_error(
                        "NO_UNDO_HISTORY",
                        "되돌릴 주사위 굴림이 없습니다.",
                        self.fsm.state.state_version,
                    )
                )
                return
            restored_state = self.undo_stack.pop()
            player_name = restored_state.current_player.playername
            with self._fsm_lock:
                messages = self.fsm.restore_state(
                    restored_state, "yacht.undo_roll", player=player_name
                )
            await self.send_many(messages)
            return

        if input_type == "RESTART":
            players = [p.to_dict() for p in self.fsm.state.players]
            await self.start_game({"players": players, "tutorial_mode": self.tutorial_mode})
            return

        await self.send(
            WSMessage.make_error("UNKNOWN_INPUT", f"알 수 없는 입력입니다: {input_type}")
        )

    async def start_game(self, payload: dict[str, Any]) -> None:
        if self._pipeline_switcher is not None:
            self._pipeline_switcher("yacht")
        players = _normalize_players(payload.get("players"))
        self.tutorial_mode = _is_tutorial_mode(payload)
        self.tutorial_complete = False
        with self._fsm_lock:
            self.undo_stack = []
            self.fsm = YachtFSM(players)
            messages = self.fsm.start()
            self._apply_tutorial_message_override(messages)
        await self.send_many(messages)
        if self._audio_manager is not None:
            await self._audio_manager.play_bgm("yacht_walk", gain_db=-12.0)

    def _apply_tutorial_message_override(self, messages: list[WSMessage]) -> None:
        if self.fsm is None or not self.tutorial_mode or self.tutorial_complete:
            return
        if self.fsm.state.phase == YachtPhase.AWAITING_ROLL.value:
            # 짧아야 한다. 이 문장은 ProgressAgent가 매 턴 그대로 읽는데,
            # 세 명이 열두 라운드를 돌면 서른여섯 번 들린다. 굴리는 법은
            # 화면 인트로에서 한 번 설명했으므로 여기서는 차례만 알린다.
            self.fsm.state.narrate(
                "yacht.tutorial_turn_start",
                player=self.fsm.state.current_player.playername,
            )
        elif self.fsm.state.phase == YachtPhase.AWAITING_KEEP.value:
            remaining = {2: "두 번", 1: "한 번"}.get(max(0, 3 - self.fsm.state.roll_count), "0번")
            self.fsm.state.narrate("yacht.roll_partial", remaining=remaining)
        else:
            return

        for message in messages:
            if message.msg_type == MsgType.STATE_UPDATE.value:
                message.payload = self.fsm.state.to_dict()
                message.state_version = self.fsm.state.state_version

    def _dev_setup_late_game(self) -> None:
        """역전 연출을 볼 수 있는 후반 상황을 만든다. 개발 모드 전용.

        현재 차례 플레이어를 2위로 앉히고 나머지를 앞세운다. 이 상태에서 한 번
        크게 넣으면 lead_change가 뜬다. 채운 칸 수는 FSM의 역전 판정 하한
        (_LEAD_CHANGE_MIN_FILLED)을 넘겨야 하므로 넉넉히 7칸을 채운다.
        """
        if self.fsm is None:
            return
        filled = ["ones", "twos", "threes", "fours", "fives", "sixes", "choice"]
        scorer_id = self.fsm.state.current_player.player_id
        others = [p for p in self.fsm.state.players if p.player_id != scorer_id]
        for player in self.fsm.state.players:
            # 덮어쓰지 않고 새로 만든다. 이미 채운 칸이 남아 있으면 사람마다
            # 채운 칸 수가 어긋나고, 그러면 먼저 다 채운 사람 차례에서 게임이 멈춘다.
            player.scores.clear()
            for category in filled:
                player.scores[category] = 2 if player.player_id == scorer_id else 4
        # 1위가 단독이어야 "뺏을 자리"가 생긴다. 공동 1위면 역전으로 치지 않는
        # 규칙이라, 선두 한 명만 살짝 올려 동점을 깬다.
        if others:
            others[0].scores["choice"] = 6
        self.fsm.state.state_version += 1
        self.fsm.state.narrate(
            "yacht.dev_late_game", player=self.fsm.state.current_player.playername
        )

    def _roll_was_recorded(self, previous_state: YachtGameState) -> bool:
        if self.fsm is None:
            return False
        return self.fsm.state.roll_count > previous_state.roll_count

    def _score_was_recorded(self, previous_state: YachtGameState, category: Any) -> bool:
        if self.fsm is None or not category:
            return False
        category_key = str(category)
        if category_key in previous_state.current_player.scores:
            return False
        scorer_id = previous_state.current_player.player_id
        scorer = next(
            (player for player in self.fsm.state.players if player.player_id == scorer_id),
            None,
        )
        return scorer is not None and category_key in scorer.scores

    def _finish_tutorial_if_complete(self, messages: list[WSMessage]) -> None:
        if self.fsm is None or not self.tutorial_mode:
            return
        if not all(len(player.scores) >= 1 for player in self.fsm.state.players):
            return
        self.tutorial_complete = True
        self.fsm.state.narrate("yacht.tutorial_complete")
        self.fsm.state.state_version += 1
        messages.append(
            WSMessage(
                msg_type="state_update",
                payload=self.fsm.state.to_dict(),
                state_version=self.fsm.state.state_version,
            )
        )

    @staticmethod
    def _roll_dice(
        current_values: list[int | None] | None = None,
        keep_mask: list[bool] | None = None,
    ) -> list[int]:
        values = list(current_values or [])
        keep = list(keep_mask or [])
        return [
            int(values[index])
            if (
                index < len(values)
                and index < len(keep)
                and keep[index]
                and values[index] is not None
            )
            else random.randint(1, 6)
            for index in range(5)
        ]

    @staticmethod
    def _is_valid_manual_dice(dice_values: Any) -> bool:
        if not isinstance(dice_values, list) or len(dice_values) != 5:
            return False
        try:
            return all(1 <= int(value) <= 6 for value in dice_values)
        except (TypeError, ValueError):
            return False

    async def send_many(self, messages: list[WSMessage]) -> None:
        for message in messages:
            if message.msg_type == MsgType.FUSION_CONTEXT.value:
                ctx = FusionContext.from_dict(message.payload)
                if self._bridge is not None:
                    self._bridge.send_fusion_context(ctx, message.state_version)
                await self._notify_agent_state_change(ctx)
            else:
                await self.send(message)

    async def _notify_agent_state_change(self, fusion_ctx: FusionContext) -> None:
        if self._agent is None or self.fsm is None:
            return
        import time as _time
        state = self.fsm.state
        players_snapshot = [
            {"player_id": p.player_id, "playername": p.playername}
            for p in state.players
        ]
        game_specific = {
            "dice_values": list(state.dice_values),
            "available_categories": list(state.available_categories),
            "roll_count": state.roll_count,
            # 문장이 아니라 발화 지시를 넘긴다. 문장 조립은 ProgressAgent가 한다.
            "narration": state.narration,
            "last_message": state.last_message,
            "tutorial_mode": self.tutorial_mode,
        }
        agent_ctx = AgentContext(
            game_type="yacht",
            fsm_state=fusion_ctx.fsm_state,
            active_player=fusion_ctx.active_player,
            players=players_snapshot,
            allowed_actors=list(fusion_ctx.allowed_actors),
            expected_events=list(fusion_ctx.expected_events),
            turn_start_time=_time.time(),
            turn_timeout=None,
            game_specific=game_specific,
        )
        await self._agent.on_state_change(agent_ctx, state_version=state.state_version)

    async def send(self, message: WSMessage) -> None:
        """FSM이 만든 메시지를 라우팅.

        audio 관련은 AudioManager 거쳐 audio_url 채워진 후 broadcast.
        """
        if message.msg_type in _AUDIO_MSG_TYPES and self._audio_manager is not None:
            await self._audio_manager.handle_outbound(message)
            return
        await self._send_raw(message)

    async def _send_raw(self, message: WSMessage) -> None:
        """AudioManager가 합성 후 다시 부르는 콜백. 또는 audio가 아닌 일반 메시지 직송."""
        if message.msg_type == "state_update":
            message.payload["can_undo"] = bool(self.undo_stack)
            message.payload["tutorial_mode"] = self.tutorial_mode
            message.payload["tutorial_complete"] = self.tutorial_complete
            # 화면 상태줄 문구. FSM은 line_id만 내보내므로 여기서 문장으로 만든다.
            # ProgressAgent가 발화할 때와 같은 카탈로그를 쓰니 화면과 음성이
            # 어긋나지 않는다 — 페르소나가 걸리면 둘 다 같이 바뀐다.
            narration = message.payload.get("narration")
            if narration:
                rendered = lines.render(
                    str(narration.get("line_id", "")), **narration.get("params", {})
                )
                if rendered:
                    message.payload["last_message"] = rendered
        # 조명은 프론트엔드와 같은 스트림을 본다. 화면이 state_update로 다시
        # 그리듯 조명도 같은 메시지로 Scene을 잡으므로 트리거 누락이 없다.
        if self._light is not None:
            self._light.on_message(message, game="yacht")
        await self.websocket.send_json(message.to_dict())


def _is_tutorial_mode(payload: dict[str, Any]) -> bool:
    mode = str(payload.get("mode") or "").lower()
    return bool(payload.get("tutorial_mode") or mode == "tutorial")


def _normalize_players(players: Any) -> list[dict[str, str]]:
    if not isinstance(players, list) or not players:
        return [
            {"player_id": "p1", "playername": "형승"},
            {"player_id": "p2", "playername": "병진"},
            {"player_id": "p3", "playername": "성민"},
        ]

    normalized: list[dict[str, str]] = []
    for index, player in enumerate(players, start=1):
        if isinstance(player, str):
            normalized.append({"player_id": f"p{index}", "playername": player})
            continue
        if not isinstance(player, dict):
            continue
        player_id = str(player.get("player_id") or player.get("id") or f"p{index}")
        name = str(player.get("playername") or player.get("name") or player_id)
        normalized.append({"player_id": player_id, "playername": name})

    return normalized or [
        {"player_id": "p1", "playername": "형승"},
        {"player_id": "p2", "playername": "병진"},
        {"player_id": "p3", "playername": "성민"},
    ]
