"""WerewolfFSM을 WebSocket 클라이언트 방식으로 구동하는 세션."""

from __future__ import annotations

import asyncio
import contextlib
import re
from collections.abc import Callable
from typing import Any

from fastapi import WebSocket

from agents.context import AgentContext
from agents.orchestrator import AgentOrchestrator
from agents.tools import lines
from audio.manager import AudioManager
from backend.dev import is_dev_mode
from bulb.controller import LightController
from core.constants import CommonEventType, MsgType
from core.envelope import WSMessage
from core.events import FusionContext, GameEvent
from games.werewolf.fsm import (
    ACTIVE_NIGHT_PHASES,
    ACTIVE_PHASE_TIMEOUT,
    PASSIVE_PHASE_DURATION,
    WerewolfFSM,
)
from games.werewolf.ontology import (
    PASSIVE_NIGHT_PHASES,
    WerewolfEventType,
    WerewolfInputType,
    WerewolfPhase,
)
from games.werewolf.state import WerewolfPlayerState

# AudioManager가 가로채는 msg_type 집합. yacht_session.py와 동일.
_AUDIO_MSG_TYPES = {
    MsgType.TTS_PLAY.value,
    MsgType.TTS_INTERRUPT.value,
    MsgType.SFX_PLAY.value,
    MsgType.BGM_PLAY.value,
    MsgType.BGM_DUCK.value,
}


def _normalize_role(role_id: str) -> str:
    """프론트가 중복 역할에 붙이는 `_1`/`_2` 접미사를 떼어 순수 역할 문자열로 만든다."""
    return re.sub(r"_\d+$", "", role_id)


class WerewolfSession:
    def __init__(
        self,
        websocket: WebSocket,
        send_fusion_context_fn: Callable[[FusionContext, int], None],
        loop: asyncio.AbstractEventLoop,
        pipeline_switcher: Callable[[str | None], None] | None = None,
        audio_manager: AudioManager | None = None,
        agent_orchestrator: AgentOrchestrator | None = None,
        seat_positions_fn: Callable[[], dict[str, tuple[float, float]]] | None = None,
        light_controller: LightController | None = None,
    ) -> None:
        self.websocket = websocket
        self._send_fusion_context = send_fusion_context_fn
        self._pipeline_switcher = pipeline_switcher
        self._loop = loop
        self._fsm: WerewolfFSM | None = None
        self._state_version: int = 0
        self._audio_manager = audio_manager
        self._agent = agent_orchestrator
        self._light = light_controller
        # 동일 객체 참조를 유지해야 detach_broadcast_if에서 is 비교가 가능.
        self._send_raw_bound = self._send_raw
        if audio_manager is not None:
            audio_manager.attach_broadcast(
                self._send_raw_bound, session_id=audio_manager.get_session_id()
            )
        # 카드 세팅 화면에서 대기 중인 게임 시작 데이터 {deck_roles, player_order}
        self._pending_setup: dict | None = None
        self._practice_mode: bool = False
        # 현재 플레이어 목록 (AgentContext 빌드용)
        self._players_snapshot: list[dict] = []
        # player_id → playername. 룰/진행 에이전트 TTS가 ID 대신 이름을 말하도록 사용.
        self._player_names: dict[str, str] = {}
        self._seat_positions_fn = seat_positions_fn
        # 현재 재생 중인 BGM 트랙 이름. phase 전환 시 같은 트랙 중복 트리거 방지.
        self._current_bgm: str | None = None

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    async def send_hello(self) -> None:
        # 멘트 카탈로그를 접속 시 통째로 준다. 프론트도 같은 문장을 화면에 그려야
        # 하는데(타이핑 애니메이션 등) 발화마다 왕복하면 타이밍이 흔들린다.
        await self.send(
            WSMessage.make_hello({"game_type": "werewolf", "lines": lines.catalog()})
        )
        # 게임 선택 즉시 파이프라인이 동작하도록 초기 FusionContext 전송
        self._state_version += 1
        self._send_fusion_context(
            FusionContext(
                fsm_state="card_setup",
                game_type="werewolf",
                active_player=None,
                allowed_actors=[],
                expected_events=[CommonEventType.GESTURE_CONFIRMED],
            ),
            self._state_version,
        )

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

        # frontend bench hook → backend bench_log로 통합.
        if input_type == "bench_trace":
            from benchmarks.relay import handle_bench_trace
            handle_bench_trace(payload)
            return

        if input_type == "START_CARD_SETUP":
            await self._start_card_setup(payload)
            return

        if input_type == "CARD_SETUP_DONE":
            await self._finish_card_setup()
            return

        if input_type == "CARD_SETUP_CONFIRM_READY":
            await self._card_setup_confirm_ready()
            return

        if input_type == "NARRATION_REQUEST":
            # 프론트가 문장이 아니라 line_id를 보낸다. 문장은 백엔드가 소유하므로
            # 페르소나를 바꾸면 프론트를 건드리지 않아도 말투가 바뀐다.
            text = lines.render(
                str(payload.get("line_id", "")), **dict(payload.get("params") or {})
            )
            if text and self._audio_manager is not None:
                sv = self._fsm.state.state_version if self._fsm is not None else 0
                await self._audio_manager.enqueue_tts(text=text, state_version=sv)
            return

        if input_type == "TTS_REQUEST":
            text = payload.get("text", "")
            if text and self._audio_manager is not None:
                sv = self._fsm.state.state_version if self._fsm is not None else 0
                await self._audio_manager.enqueue_tts(text=text, state_version=sv)
            return

        if input_type in ("RESTART", "reset_game"):
            self._fsm = None
            self._pending_setup = None
            self._player_names = {}
            if self._audio_manager is not None and self._current_bgm is not None:
                await self._audio_manager.stop_bgm()
            self._current_bgm = None
            if self._pipeline_switcher is not None:
                self._pipeline_switcher(None)
            return

        if self._fsm is None:
            await self.send(WSMessage.make_error("GAME_NOT_STARTED", "한밤이 시작되지 않았습니다."))
            return

        # 개발 모드 전용. 밤 페이즈는 타이머로 넘어가는데 조명·TTS를 조율하려면
        # 페이즈 하나를 수십 번 다시 봐야 해서 8~15초를 매번 기다릴 수 없다.
        if input_type == "DEV_NEXT_PHASE":
            if not is_dev_mode():
                return
            await self.send_many(self._fsm._advance_to_next_phase())
            return

        if input_type in (
            WerewolfInputType.ADD_30_SEC,
            WerewolfInputType.START_NOW,
            WerewolfInputType.VOTE_PLAYER,
            WerewolfInputType.VOTE_RESULT_CONFIRM,
            WerewolfInputType.VOTE_COUNTDOWN_START,
        ):
            await self.send_many(self._fsm.handle_input(input_type, payload, player_id))
            return

        await self.send(
            WSMessage.make_error("UNKNOWN_INPUT", f"알 수 없는 입력입니다: {input_type}")
        )

    def get_vision_event_handler(self) -> Callable[[GameEvent, int], None]:
        """비전 스레드에서 호출될 동기 핸들러 반환. 이벤트를 asyncio 루프에 스케줄."""
        def handler(event: GameEvent, state_version: int) -> None:
            # 루프 종료 후 호출 시 무시
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(
                    self._handle_vision_event(event), self._loop
                )
        return handler

    # ── 게임 시작 (pre-game) ──────────────────────────────────────────────────

    async def _start_game(self) -> None:
        """카드 세팅이 끝난 뒤 FSM을 생성해 첫 밤을 시작한다.

        시스템은 누가 어떤 카드를 받았는지 모른다. 아는 것은 이번 판에 사용하는
        역할 덱뿐이고, 그것으로 야간 페이즈 호명 순서만 결정한다.
        """
        if self._pending_setup is None:
            return
        setup = self._pending_setup
        self._pending_setup = None

        # Benchmark hook.
        try:
            import time as _t

            from benchmarks.common.trace_setup import bench_log
            bench_log().info("game_start werewolf %.6f", _t.time())
        except Exception:
            pass

        player_order: list[str] = setup["player_order"]
        self._players_snapshot = [
            {"player_id": pid, "playername": self._player_names.get(pid, pid)}
            for pid in player_order
        ]
        ws_players = [WerewolfPlayerState(player_id=pid) for pid in player_order]
        seat_positions = self._seat_positions_fn() if self._seat_positions_fn else {}

        self._fsm = WerewolfFSM(
            players=ws_players,
            deck_roles=setup["deck_roles"],
            broadcast=self._broadcast_msg,
            seat_positions=seat_positions,
            practice_mode=self._practice_mode,
        )
        await self.send_many(self._fsm.start())

    # ── 비전 이벤트 처리 ──────────────────────────────────────────────────────

    async def _handle_vision_event(self, event: GameEvent) -> None:
        etype = event.event_type

        # 규칙 에이전트: FSM 처리 이전에 위반 감지
        if self._agent is not None:
            await self._agent.on_game_event(event)

        # 카드 세팅 화면에서의 OK 사인은 게임 시작 신호. FSM 생성 전이라 먼저 가로챈다.
        if etype == CommonEventType.GESTURE_CONFIRMED and self._pending_setup is not None:
            await self._finish_card_setup()
            return

        if self._fsm is None:
            return

        if etype in (CommonEventType.GESTURE_CONFIRMED, WerewolfEventType.VOTE_POINT):
            await self.send_many(self._fsm.handle_event(event))

    async def _notify_agent_state_change(self, fusion_ctx: FusionContext) -> None:
        if self._agent is None:
            return
        import time as _time
        timeout = None
        phase_end_warning = None
        if fusion_ctx.fsm_state == WerewolfPhase.DAY_DISCUSSION:
            timeout = 300.0
        elif (
            fusion_ctx.fsm_state in PASSIVE_NIGHT_PHASES
            and fusion_ctx.fsm_state != WerewolfPhase.NIGHT_START
            and not self._practice_mode
        ):
            timeout = float(PASSIVE_PHASE_DURATION)
            phase_end_warning = "tempo.close_eyes_again"
        elif fusion_ctx.fsm_state in ACTIVE_NIGHT_PHASES and not self._practice_mode:
            timeout = float(ACTIVE_PHASE_TIMEOUT)
            phase_end_warning = "tempo.close_eyes_again"
        agent_ctx = AgentContext(
            game_type="werewolf_practice" if self._practice_mode else "werewolf",
            fsm_state=fusion_ctx.fsm_state,
            active_player=fusion_ctx.active_player,
            players=self._players_snapshot,
            allowed_actors=list(fusion_ctx.allowed_actors),
            expected_events=list(fusion_ctx.expected_events),
            turn_start_time=_time.time(),
            turn_timeout=timeout,
            phase_end_warning_line=phase_end_warning,
        )
        await self._agent.on_state_change(agent_ctx, state_version=self._state_version)

    async def _start_card_setup(self, payload: dict) -> None:
        """역할 덱 선택 완료 → 카드 세팅 안내 화면으로 진입.

        여기서 받은 덱은 야간 페이즈 호명 순서를 정하는 데만 쓰인다. 어떤 카드가
        누구에게 갔고 무엇이 센터에 깔렸는지는 시스템이 알지 못한다.
        """
        player_order = payload.get("player_order", [])
        if not player_order:
            return
        deck_roles = [_normalize_role(r) for r in payload.get("selected_roles", [])]
        self._practice_mode = bool(payload.get("practice_mode", False))
        # 프론트가 함께 보낸 이름 매핑 저장 (룰/진행 에이전트 TTS용). 누락 시 빈 dict.
        self._player_names = {
            str(p["player_id"]): str(p.get("playername") or p["player_id"])
            for p in payload.get("players", [])
            if p.get("player_id")
        }
        self._pending_setup = {
            "deck_roles": deck_roles,
            "player_order": list(player_order),
        }
        self._state_version += 1
        self._send_fusion_context(
            FusionContext(
                fsm_state="card_setup",
                game_type="werewolf_practice" if self._practice_mode else "werewolf",
                active_player=None,
                allowed_actors=[],
                expected_events=[CommonEventType.GESTURE_CONFIRMED],
            ),
            self._state_version,
        )
        await self.send(WSMessage(
            msg_type=MsgType.STATE_UPDATE.value,
            payload={"phase": "card_setup", "deck_roles": deck_roles},
            state_version=self._state_version,
        ))

    async def _card_setup_confirm_ready(self) -> None:
        # confirming 단계 진입 시 gesture 가드(_gesture_confirmed_emitted)를 초기화.
        # card_setup 문장 재생 중 OK 사인이 감지돼 가드에 남으면 confirming 단계에서 차단되므로,
        # fsm_state를 "card_setup_confirm"으로 바꿔 FusionEngine 가드를 지운다.
        self._state_version += 1
        self._send_fusion_context(
            FusionContext(
                fsm_state="card_setup_confirm",
                game_type="werewolf_practice" if self._practice_mode else "werewolf",
                active_player=None,
                allowed_actors=[],
                expected_events=[CommonEventType.GESTURE_CONFIRMED],
            ),
            self._state_version,
        )

    async def _finish_card_setup(self) -> None:
        """CardSetupGuide 완료 → 곧바로 첫 밤 시작."""
        await self._start_game()

    async def _broadcast_msg(self, msg: WSMessage) -> None:
        """WerewolfFSM 타이머가 호출하는 broadcast 콜백. audio 메시지도 여기서 흐를 수 있음."""
        # disconnect 후 타이머가 남아 있을 때 조용히 종료
        with contextlib.suppress(Exception):
            await self.send_many([msg])

    async def send_many(self, messages: list[WSMessage]) -> None:
        for msg in messages:
            if msg.msg_type == MsgType.FUSION_CONTEXT.value:
                ctx = FusionContext.from_dict(msg.payload)
                self._send_fusion_context(ctx, msg.state_version)
                self._state_version = msg.state_version
                await self._notify_agent_state_change(ctx)
            else:
                if (
                    msg.msg_type == MsgType.STATE_UPDATE.value
                    and isinstance(msg.payload, dict)
                ):
                    await self._maybe_switch_bgm(msg.payload.get("phase"))
                await self.send(msg)

    async def _maybe_switch_bgm(self, phase: str | None) -> None:
        """phase 전환 시 적절한 BGM으로 교체. 같은 트랙이면 no-op."""
        if not phase or self._audio_manager is None:
            return
        target: str | None
        if phase.startswith("night_"):
            target = "werewolf_night"
        elif phase in ("day_discussion", "vote", "vote_countdown"):
            target = "werewolf_day"
        else:
            # result, card_setup 등 → 무음.
            target = None
        if target == self._current_bgm:
            return
        self._current_bgm = target
        if target is None:
            await self._audio_manager.stop_bgm()
        else:
            await self._audio_manager.play_bgm(target, gain_db=-14.0)

    async def send(self, message: WSMessage) -> None:
        """audio 메시지면 AudioManager 거쳐 audio_url 채운 후 broadcast."""
        if message.msg_type in _AUDIO_MSG_TYPES and self._audio_manager is not None:
            await self._audio_manager.handle_outbound(message)
            return
        await self._send_raw(message)

    async def _send_raw(self, message: WSMessage) -> None:
        # 조명은 프론트엔드와 같은 스트림을 본다. 페이즈 이름이 곧 Scene 키다.
        if self._light is not None:
            self._light.on_message(message, game="werewolf")
        await self.websocket.send_json(message.to_dict())
