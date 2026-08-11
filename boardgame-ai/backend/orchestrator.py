"""백엔드 오케스트레이터.

플레이어 등록·좌석 배정·게임 선택 등 로비 흐름을 관리한다.
게임별 FSM은 각 게임의 WebSocket 세션(/ws/yacht, /ws/werewolf)에서 직접 구동한다.
비전 이벤트 중 게임별 이벤트는 해당 세션 핸들러로 포워딩한다.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable

from audio.manager import AudioManager
from backend.state import build_state_snapshot
from core.constants import CommonEventType, CommonPhase
from core.envelope import WSMessage
from core.events import FusionContext, GameEvent
from core.models import SeatZone
from core.player_manager import PlayerManager
from games.werewolf.ontology import WerewolfEventType


class Orchestrator:
    def __init__(self, send_fusion_context_fn: Callable[[FusionContext, int], None]) -> None:
        self._pm = PlayerManager()
        self._send_fusion_context = send_fusion_context_fn
        self._lock = threading.Lock()
        self._broadcast_cb: Callable[[dict], None] | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._phase = CommonPhase.PLAYER_SETUP
        self._state_version = 0
        self._seat_step = "idle"
        self._pending_register_id: str | None = None
        self._players_listener: Callable[[list], None] | None = None
        self._pipeline_switcher: Callable[[str | None], None] | None = None
        self._werewolf_event_handler: Callable[[GameEvent, int], None] | None = None
        self._gesture_confirmed: str | None = None
        self._audio_manager: AudioManager | None = None
        # 같은 sound 키가 연속해서 들어와도 frontend React가 매번 트리거하도록 시퀀스 증가.
        self._sound_seq = 0

    def set_broadcast(
        self,
        cb: Callable[[dict], None],
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._broadcast_cb = cb
        self._loop = loop

    def set_pipeline_switcher(self, cb: Callable[[str | None], None]) -> None:
        self._pipeline_switcher = cb

    def set_players_listener(self, cb: Callable[[list], None]) -> None:
        self._players_listener = cb

    def set_werewolf_event_handler(
        self, handler: Callable[[GameEvent, int], None] | None
    ) -> None:
        """WerewolfSession이 활성화될 때 비전 이벤트 포워딩 핸들러 등록."""
        self._werewolf_event_handler = handler

    def set_audio_manager(self, audio_manager: AudioManager) -> None:
        """오디오 매니저 주입. 좌석 등록 완료/플레이어 변경 시 캐시 prewarm/wipe에 사용."""
        self._audio_manager = audio_manager

    def _notify_players(self) -> None:
        if self._players_listener is None:
            return
        registered = [p for p in self._pm.state.players if p.seat_zone is not None]
        with contextlib.suppress(Exception):
            self._players_listener(registered)

    # ── 비전 이벤트 소비 ─────────────────────────────────────────────────────

    def handle_game_event(self, event: GameEvent, state_version: int) -> None:
        if event.event_type == CommonEventType.SEAT_RIGHT_REGISTERED:
            self._handle_seat_right_registered(event)
        elif event.event_type == CommonEventType.SEAT_REGISTERED:
            self._handle_seat_registered(event)
        elif event.event_type == CommonEventType.GESTURE_CONFIRMED:
            self._handle_gesture_confirmed(event)
            # 웨어울프 세션이 연결돼 있으면 함께 전달.
            # card_setup 완료 신호이자 야간 페이즈 진행 신호로 쓰인다.
            if self._werewolf_event_handler is not None:
                self._werewolf_event_handler(event, state_version)
        elif event.event_type == WerewolfEventType.VOTE_POINT:
            if self._werewolf_event_handler is not None:
                self._werewolf_event_handler(event, state_version)

    def _handle_seat_right_registered(self, event: GameEvent) -> None:
        actor_id = event.actor_id
        if not actor_id:
            return
        with self._lock:
            if self._pm.state.registering_player_id != actor_id:
                return
            self._seat_step = "right_done"
            self._sound_seq += 1
            # 오른손 등록 단계에도 효과음 발행. sound_seq로 React useEffect가 매번 트리거되게.
            snapshot = self._snapshot(sound="registered")
        self._broadcast(snapshot)

    def _handle_seat_registered(self, event: GameEvent) -> None:
        data = event.data or {}
        actor_id = event.actor_id
        seat_zone_d = data.get("seat_zone")
        if not actor_id or not seat_zone_d:
            return

        seat_zone = SeatZone.from_dict(seat_zone_d)

        with self._lock:
            try:
                self._pm.record_seat(actor_id, seat_zone)
            except KeyError:
                return

            self._phase = CommonPhase.PLAYER_SETUP
            self._seat_step = "completed"
            self._sound_seq += 1
            snapshot = self._snapshot(sound="registered")

        self._push_context(CommonPhase.PLAYER_SETUP)
        self._notify_players()
        self._broadcast(snapshot)
        # 좌석 등록 완료 시점에 session prewarm 트리거(멱등). 매번 호출돼도
        # session_id가 결정적이라 두 번째부터는 캐시 hit으로 무료.
        self._prewarm_audio_session()

    def _prewarm_audio_session(self) -> None:
        if self._audio_manager is None:
            return
        names = [
            p.playername for p in self._pm.state.players
            if p.seat_zone is not None and p.playername
        ]
        if not names or self._loop is None:
            return
        # 비전 스레드에서 호출될 수 있으니 asyncio 루프에 스케줄.
        asyncio.run_coroutine_threadsafe(
            self._prewarm_audio_session_async(names), self._loop
        )

    async def _prewarm_audio_session_async(self, names: list[str]) -> None:
        if self._audio_manager is None:
            return
        self._audio_manager.prewarm_session_async(names)

    def _handle_gesture_confirmed(self, event: GameEvent) -> None:
        actor_id = event.actor_id
        if not actor_id:
            return
        with self._lock:
            self._gesture_confirmed = actor_id
            snapshot = self._snapshot()
            self._gesture_confirmed = None
        self._broadcast(snapshot)

    # ── HTTP 핸들러 (routes/players.py에서 호출) ──────────────────────────────

    def add_player(self, playername: str) -> dict:
        with self._lock:
            pid = self._pm.add_player(playername)
            snapshot = self._snapshot()
        self._broadcast(snapshot)
        return {"player_id": pid}

    def start_registration(self) -> dict:
        with self._lock:
            pid = self._pm.add_pending_player()
            self._pm.start_seat_registration(pid)
            self._phase = CommonPhase.SEAT_REGISTER
            self._seat_step = "right_pending"
            self._pending_register_id = pid
            snapshot = self._snapshot()
        self._push_context(CommonPhase.SEAT_REGISTER, active_player=pid)
        self._broadcast(snapshot)
        return {"player_id": pid}

    def finalize_player(self, player_id: str, playername: str) -> None:
        with self._lock:
            self._pm.edit_playername(player_id, playername)
            self._seat_step = "idle"
            if self._pending_register_id == player_id:
                self._pending_register_id = None
            snapshot = self._snapshot()
        self._notify_players()
        self._broadcast(snapshot)

    def edit_player(self, player_id: str, playername: str) -> None:
        with self._lock:
            self._pm.edit_playername(player_id, playername)
            snapshot = self._snapshot()
        self._notify_players()
        self._broadcast(snapshot)

    def remove_player(self, player_id: str) -> None:
        with self._lock:
            self._pm.remove_player(player_id)
            if self._pending_register_id == player_id:
                self._pending_register_id = None
            if self._pm.state.registering_player_id == player_id:
                self._pm.state.registering_player_id = None
                self._pm.state.pending_wrists = {}
            if (
                self._pm.state.registering_player_id is None
                and self._phase == CommonPhase.SEAT_REGISTER
            ):
                self._phase = CommonPhase.PLAYER_SETUP
                self._seat_step = "idle"
            snapshot = self._snapshot()
        if self._phase == CommonPhase.PLAYER_SETUP:
            self._push_context(CommonPhase.PLAYER_SETUP)
        self._notify_players()
        self._broadcast(snapshot)

    def get_players_list(self) -> list[dict]:
        with self._lock:
            return [p.to_dict() for p in self._pm.state.players]

    def cancel_seat_registration(self, player_id: str | None = None) -> None:
        with self._lock:
            target_id = player_id or self._pending_register_id or self._pm.state.registering_player_id
            self._pm.state.registering_player_id = None
            self._pm.state.pending_wrists = {}
            self._pending_register_id = None
            if self._phase == CommonPhase.SEAT_REGISTER:
                self._phase = CommonPhase.PLAYER_SETUP
                self._seat_step = "idle"
            if target_id:
                self._pm.state.players = [
                    player
                    for player in self._pm.state.players
                    if not (
                        player.player_id == target_id
                        and not player.playername
                        and player.seat_zone is None
                    )
                ]
            snapshot = self._snapshot()
        self._push_context(CommonPhase.PLAYER_SETUP)
        self._notify_players()
        self._broadcast(snapshot)

    def start_seat_registration(self, player_id: str) -> None:
        with self._lock:
            self._pm.restart_seat_registration(player_id)
            self._phase = CommonPhase.SEAT_REGISTER
            self._seat_step = "right_pending"
            snapshot = self._snapshot()
        self._push_context(CommonPhase.SEAT_REGISTER, active_player=player_id)
        self._notify_players()
        self._broadcast(snapshot)

    def current_snapshot(self) -> dict:
        with self._lock:
            return self._snapshot()

    # ── WebSocket input 처리 ──────────────────────────────────────────────────

    def handle_input(self, input_type: str, data: dict, player_id: str | None = None) -> None:
        # 오디오 재생 완료/중단 ack — tablet 채널에서도 들어올 수 있음 (App 레벨 useAudioPlayer).
        if input_type == "audio_ack" and self._audio_manager is not None and self._loop is not None:
            pbid = str(data.get("playback_id", ""))
            status = str(data.get("status", ""))
            if pbid:
                asyncio.run_coroutine_threadsafe(
                    self._audio_manager.handle_ack(pbid, status), self._loop,
                )
            return

        # frontend bench hook → backend bench_log (tablet 채널에서 들어옴).
        if input_type == "bench_trace":
            from benchmarks.relay import handle_bench_trace
            handle_bench_trace(data)
            return
        if input_type == "start_registration":
            self.start_registration()
        elif input_type == "finalize_player":
            pid = data.get("player_id")
            name = data.get("playername", "")
            if pid and name:
                self.finalize_player(pid, name)
        elif input_type == "start_seat_registration":
            pid = data.get("player_id")
            if pid:
                self.start_seat_registration(pid)
        elif input_type == "cancel_seat_registration":
            self.cancel_seat_registration(data.get("player_id"))
        elif input_type == "player_add":
            name = data.get("playername", "")
            if name:
                self.add_player(name)
        elif input_type == "player_edit":
            pid = data.get("player_id")
            name = data.get("playername", "")
            if pid and name:
                self.edit_player(pid, name)
        elif input_type == "player_remove":
            pid = data.get("player_id")
            if pid:
                self.remove_player(pid)
        elif input_type == "select_game":
            game_type = data.get("game_type", "")
            self._handle_select_game(game_type)
        elif input_type == "reset_game":
            with self._lock:
                self._phase = CommonPhase.PLAYER_SETUP
                snapshot = self._snapshot()
            if self._pipeline_switcher is not None:
                self._pipeline_switcher(None)
            self._push_context(CommonPhase.PLAYER_SETUP)
            self._broadcast(snapshot)

    # ── 게임 선택 ────────────────────────────────────────────────────────────

    def _handle_select_game(self, game_type: str) -> None:
        with self._lock:
            self._phase = CommonPhase.GAME_SELECT
            snapshot = self._snapshot()
        self._broadcast(snapshot)

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _snapshot(self, sound: str | None = None) -> dict:
        registering = self._pending_register_id or self._pm.state.registering_player_id
        return build_state_snapshot(
            players=self._pm.state.players,
            phase=self._phase,
            registering_player_id=registering,
            seat_step=self._seat_step,
            sound=sound,
            sound_seq=self._sound_seq,
            gesture_confirmed=self._gesture_confirmed,
        )

    def _push_context(self, phase: str, active_player: str | None = None) -> None:
        self._state_version += 1
        if phase == CommonPhase.SEAT_REGISTER:
            expected = [
                CommonEventType.SEAT_RIGHT_REGISTERED,
                CommonEventType.SEAT_REGISTERED,
            ]
            allowed = [active_player] if active_player else []
        elif phase == CommonPhase.PLAYER_SETUP:
            expected = [CommonEventType.GESTURE_CONFIRMED]
            allowed = []
        else:
            expected = []
            allowed = [active_player] if active_player else []
        ctx = FusionContext(
            fsm_state=phase,
            game_type=None,
            active_player=active_player,
            allowed_actors=allowed,
            expected_events=expected,
            params={"gesture_stabilization_frames": 3}
            if phase == CommonPhase.SEAT_REGISTER
            else {},
        )
        self._send_fusion_context(ctx, self._state_version)

    def _broadcast(self, snapshot: dict) -> None:
        if self._broadcast_cb is None or self._loop is None:
            return
        cb = self._broadcast_cb
        asyncio.run_coroutine_threadsafe(_call_async(cb, snapshot), self._loop)


async def _call_async(cb: Callable[[dict], None], snapshot: dict) -> None:
    result = cb(snapshot)
    if asyncio.iscoroutine(result):
        await result
