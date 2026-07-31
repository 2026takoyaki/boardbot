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
from audio.manager import AudioManager
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
    WerewolfRole,
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
    return re.sub(r"_\d+$", "", role_id)


# 역할 등록 플레이어 전환 타이밍
REG_TRANSITION_MAX_WAIT = 9.0    # 프론트 진행 신호(TTS 종료+3초)와 카드 감지가 모두 유실됐을 때의 안전 데드라인(초)
REG_CARD_PLACED_ADVANCE = 3.0    # 카드 내려놓기 감지 후 진행까지 유예(초). 안내 TTS가 잘리지 않도록 두며, 데드라인 이내로만 적용.


# 비전 감지 여부와 무관하게 본인 카드가 항상 바뀌는 역할
_SELF_SWAP_ROLES: frozenset[str] = frozenset({
    WerewolfRole.ROBBER,
    WerewolfRole.DRUNK,
    WerewolfRole.DOPPELGANGER,
})


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
        self._role_reg: dict | None = None
        self._pending_game_data: dict | None = None
        self._audio_manager = audio_manager
        self._agent = agent_orchestrator
        self._light = light_controller
        # 동일 객체 참조를 유지해야 detach_broadcast_if에서 is 비교가 가능.
        self._send_raw_bound = self._send_raw
        if audio_manager is not None:
            audio_manager.attach_broadcast(
                self._send_raw_bound, session_id=audio_manager.get_session_id()
            )
        self._pending_role_reg: dict | None = None
        self._practice_mode: bool = False
        self._role_reveal: dict | None = None
        # 역할 등록 전환: 카드 내려놓기 대기 중인 다음 플레이어 / 폴백 타이머
        self._pending_next_reg_player: str | None = None
        self._reg_transition_task: asyncio.Task | None = None
        # 전환 진입 시 1회만 정하는 하드 데드라인(루프 시계). 어떤 이벤트도 이 시점을 넘기지 못한다.
        self._reg_transition_deadline: float = 0.0
        # 현재 플레이어 목록 (AgentContext 빌드용)
        self._players_snapshot: list[dict] = []
        # player_id → playername. 룰/진행 에이전트 TTS가 ID 대신 이름을 말하도록 사용.
        self._player_names: dict[str, str] = {}
        self._seat_positions_fn = seat_positions_fn
        # 현재 재생 중인 BGM 트랙 이름. phase 전환 시 같은 트랙 중복 트리거 방지.
        self._current_bgm: str | None = None

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    async def send_hello(self) -> None:
        await self.send(WSMessage.make_hello({"game_type": "werewolf"}))
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

        if input_type == "START_ROLE_REGISTRATION":
            await self._start_role_registration(payload)
            return

        if input_type == "CONFIRM_ROLE":
            await self._confirm_role(player_id, payload)
            return

        if input_type == "REG_TRANSITION_ADVANCE":
            await self._advance_reg_transition_now()
            return

        if input_type == "CARD_SETUP_DONE":
            await self._finish_card_setup()
            return

        if input_type == "CARD_SETUP_CONFIRM_READY":
            await self._card_setup_confirm_ready()
            return

        if input_type == "BACK_TO_CARD_SETUP":
            await self._back_to_card_setup()
            return

        if input_type == "BACK_TO_PREV_PLAYER":
            await self._back_to_prev_player()
            return

        if input_type == "ROLE_REVEAL_CONFIRM":
            await self._confirm_role_reveal(player_id, payload)
            return

        if input_type == "TTS_REQUEST":
            text = payload.get("text", "")
            if text and self._audio_manager is not None:
                sv = self._fsm.state.state_version if self._fsm is not None else 0
                await self._audio_manager.enqueue_tts(text=text, state_version=sv)
            return

        if input_type == "START_WEREWOLF_GAME":
            await self._start_game(payload)
            return

        if input_type in ("RESTART", "reset_game"):
            self._fsm = None
            self._role_reg = None
            self._pending_game_data = None
            self._pending_role_reg = None
            self._role_reveal = None
            self._player_names = {}
            self._pending_next_reg_player = None
            if self._reg_transition_task and not self._reg_transition_task.done():
                self._reg_transition_task.cancel()
            self._reg_transition_task = None
            if self._audio_manager is not None and self._current_bgm is not None:
                await self._audio_manager.stop_bgm()
            self._current_bgm = None
            if self._pipeline_switcher is not None:
                self._pipeline_switcher(None)
            return

        if self._fsm is None:
            await self.send(WSMessage.make_error("GAME_NOT_STARTED", "한밤이 시작되지 않았습니다."))
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

    # ── 역할 등록 (pre-game) ──────────────────────────────────────────────────

    async def _start_role_registration(self, payload: dict) -> None:
        selected_roles = payload.get("selected_roles", [])
        player_order = payload.get("player_order", [])
        if not player_order:
            return
        normalized_roles = [_normalize_role(r) for r in selected_roles]
        self._practice_mode = bool(payload.get("practice_mode", False))
        # 프론트가 함께 보낸 이름 매핑 저장 (룰/진행 에이전트 TTS용). 누락 시 빈 dict.
        self._player_names = {
            str(p["player_id"]): str(p.get("playername") or p["player_id"])
            for p in payload.get("players", [])
            if p.get("player_id")
        }
        self._pending_role_reg = {
            "selected_roles": normalized_roles,
            "player_order": player_order,
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
            payload={"phase": "card_setup", "all_roles": normalized_roles},
            state_version=self._state_version,
        ))

    async def _confirm_role(self, player_id: str | None, payload: dict | None = None) -> None:
        if self._role_reg is None or player_id is None:
            return
        # 프론트에서 수동 선택한 역할 우선, 없으면 비전 감지 결과 사용 (_1/_2 suffix 정규화)
        payload_role = (payload or {}).get("role")
        detected = self._role_reg.get("detected_role")
        role = _normalize_role(str(payload_role)) if payload_role else detected
        if not role:
            return

        # Benchmark hook: 역할 등록 인식 정확도. match=1 → 비전 감지값을 그대로 확정,
        # match=0 → 비전이 미감지했거나(detected None) 사용자가 수동 정정.
        try:
            from benchmarks.common.trace_setup import bench_log
            match = 1 if (detected and role == _normalize_role(str(detected))) else 0
            bench_log().info("role_recognition reg match=%d", match)
        except Exception:
            pass

        self._role_reg["confirmed_roles"][player_id] = role
        next_index = self._role_reg["player_index"] + 1
        player_order = self._role_reg["player_order"]

        if next_index < len(player_order):
            next_player = player_order[next_index]
            await self._start_reg_transition(next_player)
        else:
            confirmed = dict(self._role_reg["confirmed_roles"])
            all_roles_snapshot = list(self._role_reg["all_roles"])
            working = list(all_roles_snapshot)
            for role in confirmed.values():
                if role in working:
                    working.remove(role)
            center_cards = working[:3]
            players_data = [
                {
                    "player_id": pid,
                    "role": confirmed[pid],
                    "playername": self._player_names.get(pid, pid),
                }
                for pid in player_order
            ]
            self._role_reg = None
            await self._start_game({
                "players": players_data,
                "center_cards": center_cards,
                "all_roles": all_roles_snapshot,
            })

    async def _start_reg_transition(self, next_player: str) -> None:
        """역할 확인 후 다음 플레이어 전환 대기 상태로 진입.

        진행 페이싱은 프론트(RoleRegTransition)가 주도한다. 프론트는 "카드를 본인 앞에
        엎어두고 다시 눈을 감아주세요" 안내 TTS가 끝나고 3초 뒤 REG_TRANSITION_ADVANCE를
        보내고, 그때 다음 플레이어로 진행한다. 아래 데드라인은 그 신호가 유실됐을 때만 쓰는
        안전장치이다.
        """
        self._pending_next_reg_player = next_player
        # 프론트 진행 신호가 유실됐을 때만 발동하는 안전 데드라인.
        self._reg_transition_deadline = self._loop.time() + REG_TRANSITION_MAX_WAIT
        self._schedule_reg_advance(self._reg_transition_deadline)
        # 비전이 role_reg_transition 페이즈에서 카드 안정/불안정을 감지하도록 FusionContext 전송
        self._state_version += 1
        self._send_fusion_context(
            FusionContext(
                fsm_state="role_reg_transition",
                game_type="werewolf_practice" if self._practice_mode else "werewolf",
                active_player=None,
                allowed_actors=[],
                expected_events=[
                    WerewolfEventType.CARD_PLACED_DOWN,
                    WerewolfEventType.CARD_UNSTABLE,
                ],
                reject_events=[WerewolfEventType.ROLE_DETECTED],
                valid_targets=None,
                zones={},
                anchors={},
                params={},
            ),
            self._state_version,
        )

    def _schedule_reg_advance(self, target_time: float) -> None:
        """target_time(루프 시계)에 다음 플레이어로 진행하도록 타이머를 (재)설정한다."""
        if self._reg_transition_task and not self._reg_transition_task.done():
            self._reg_transition_task.cancel()
        delay = max(0.0, target_time - self._loop.time())
        self._reg_transition_task = asyncio.create_task(
            self._advance_to_next_reg_player(delay)
        )

    async def _advance_to_next_reg_player(self, delay: float) -> None:
        """delay초 후 다음 플레이어 역할 등록으로 진행."""
        try:
            await asyncio.sleep(delay)
            next_player = self._pending_next_reg_player
            if next_player is None or self._role_reg is None:
                return
            self._pending_next_reg_player = None
            self._reg_transition_task = None
            self._role_reg["player_index"] = self._role_reg["player_order"].index(next_player)
            self._role_reg["player_id"] = next_player
            self._role_reg["detected_role"] = None
            self._role_reg["detected_low_confidence"] = False
            await self._push_role_reg_context(next_player)
            await self._broadcast_role_reg()
        except asyncio.CancelledError:
            pass

    async def _advance_reg_transition_now(self) -> None:
        """프론트가 안내 TTS 종료 + 3초 경과를 알림(REG_TRANSITION_ADVANCE) → 즉시 진행."""
        if self._pending_next_reg_player is None:
            return
        self._schedule_reg_advance(self._loop.time())

    async def _handle_card_placed_down(self) -> None:
        """CARD_PLACED_DOWN 수신: 카드를 안정적으로 내려놓았으니 다음 플레이어로 진행한다.
        안내 TTS가 잘리지 않도록 REG_CARD_PLACED_ADVANCE초 유예를 두며, 진행 시점은
        진입 시 정한 하드 데드라인(REG_TRANSITION_MAX_WAIT)을 넘기지 않는다."""
        if self._pending_next_reg_player is None:
            return
        target = min(
            self._loop.time() + REG_CARD_PLACED_ADVANCE,
            self._reg_transition_deadline,
        )
        self._schedule_reg_advance(target)

    async def _handle_card_unstable(self) -> None:
        """CARD_UNSTABLE 수신. 카드가 다시 흔들려도 이미 예약된 진행은 되돌리지 않는다.
        (추적 jitter로 CARD_UNSTABLE이 반복돼도 전환이 무한 지연되는 것을 방지)"""
        return

    async def _start_game(self, payload: dict) -> None:
        # Benchmark hook.
        try:
            import time as _t

            from benchmarks.common.trace_setup import bench_log
            bench_log().info("game_start werewolf %.6f", _t.time())
        except Exception:
            pass
        players_data = payload.get("players", [])
        center_cards = payload.get("center_cards", [])
        self._players_snapshot = [
            {"player_id": p["player_id"], "playername": p.get("playername", p["player_id"])}
            for p in players_data
        ]
        ws_players = [
            WerewolfPlayerState(
                player_id=p["player_id"],
                original_role=p["role"],
                current_role=p["role"],
            )
            for p in players_data
        ]
        seat_positions = self._seat_positions_fn() if self._seat_positions_fn else {}

        self._fsm = WerewolfFSM(
            players=ws_players,
            center_cards=center_cards,
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

        if etype == WerewolfEventType.ROLE_DETECTED:
            await self._handle_role_detected(event)
            return

        if etype == WerewolfEventType.CARD_PLACED_DOWN:
            await self._handle_card_placed_down()
            return

        if etype == WerewolfEventType.CARD_UNSTABLE:
            await self._handle_card_unstable()
            return

        if etype == CommonEventType.GESTURE_CONFIRMED:
            if self._pending_role_reg is not None:
                await self._finish_card_setup()
            return

        if self._fsm is None:
            return

        if etype in (
            WerewolfEventType.CARD_PEEK,
            WerewolfEventType.CARD_SWAP,
            WerewolfEventType.VOTE_POINT,
        ):
            await self.send_many(self._fsm.handle_event(event))

    async def _handle_role_detected(self, event: GameEvent) -> None:
        role = (event.data or {}).get("role")
        if not role:
            return
        if self._role_reg is not None:
            if self._role_reg["detected_role"] is not None:
                return
            # 등록 단계에는 활성 플레이어 1명만 카드를 카메라에 보여주므로, 좌석 매칭이
            # 어긋나도(card_player_id 불일치/None) 감지된 역할을 활성 플레이어로 그대로 등록한다.
            # 좌석 기반 거부 게이트는 인식률을 크게 떨어뜨려 제거했다(인식 테스트 모듈과 동일 동작).
            self._role_reg["detected_role"] = role
            # 저신뢰 감지면 프론트가 자동 확인을 끄고 수정 화면에 머물도록 플래그 전달.
            self._role_reg["detected_low_confidence"] = bool(
                (event.data or {}).get("low_confidence", False)
            )
            await self._broadcast_role_reg()
            return
        if self._role_reveal is not None:
            if self._role_reveal["detected_role"] is not None:
                return
            self._role_reveal["detected_role"] = role
            self._role_reveal["detected_low_confidence"] = bool(
                (event.data or {}).get("low_confidence", False)
            )
            await self._broadcast_role_reveal()
            return

    # ── 내부 헬퍼 ────────────────────────────────────────────────────────────

    async def _push_role_reg_context(self, player_id: str) -> None:
        self._state_version += 1
        # 이 게임에 포함된 역할로만 인식 후보를 제한 (비전이 게임 외 역할로 오분류해도 배제).
        in_game_roles = sorted({
            _normalize_role(str(r)).lower()
            for r in (self._role_reg or {}).get("all_roles", [])
        })
        ctx = FusionContext(
            fsm_state="role_registration",
            game_type="werewolf_practice" if self._practice_mode else "werewolf",
            active_player=player_id,
            allowed_actors=[player_id],
            expected_events=[WerewolfEventType.ROLE_DETECTED],
            reject_events=[
                WerewolfEventType.CARD_PEEK,
                WerewolfEventType.CARD_SWAP,
                WerewolfEventType.VOTE_POINT,
            ],
            valid_targets=None,
            zones={},
            anchors={},
            params={"stabilization_frames": 1, "in_game_roles": in_game_roles},
        )
        self._send_fusion_context(ctx, self._state_version)
        await self._notify_agent_state_change(ctx)

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
            phase_end_warning = "눈을 다시 감아주세요."
        elif fusion_ctx.fsm_state in ACTIVE_NIGHT_PHASES and not self._practice_mode:
            timeout = float(ACTIVE_PHASE_TIMEOUT)
            phase_end_warning = "눈을 다시 감아주세요."
        agent_ctx = AgentContext(
            game_type="werewolf_practice" if self._practice_mode else "werewolf",
            fsm_state=fusion_ctx.fsm_state,
            active_player=fusion_ctx.active_player,
            players=self._players_snapshot,
            allowed_actors=list(fusion_ctx.allowed_actors),
            expected_events=list(fusion_ctx.expected_events),
            turn_start_time=_time.time(),
            turn_timeout=timeout,
            phase_end_warning=phase_end_warning,
        )
        await self._agent.on_state_change(agent_ctx, state_version=self._state_version)

    async def _start_role_reveal(self) -> None:
        """투표 종료 후 최종 역할 확인 단계 시작. 카드가 교환된 플레이어만 순서대로 재인식."""
        if self._fsm is None:
            return
        # 비전 감지 스왑 피해자 + 본인 카드가 항상 바뀌는 역할 보유자
        swap_players = [
            p.player_id for p in self._fsm.state.players
            if p.current_role != p.original_role
            or p.original_role in _SELF_SWAP_ROLES
        ]
        if not swap_players:
            # 실제로 교환된 카드가 없으면 바로 결과로 진행
            await self.send_many(
                self._fsm.handle_input(WerewolfInputType.START_NOW, {}, None)
            )
            return
        first_player = swap_players[0]
        self._role_reveal = {
            "player_order": swap_players,
            "player_index": 0,
            "player_id": first_player,
            "detected_role": None,
        }
        await self._push_role_reveal_context(first_player)
        await self._broadcast_role_reveal()

    async def _confirm_role_reveal(
        self, player_id: str | None, payload: dict | None = None
    ) -> None:
        """플레이어의 최종 역할을 확정하고 FSM current_role을 업데이트한다."""
        if self._role_reveal is None or player_id is None or self._fsm is None:
            return
        detected = self._role_reveal.get("detected_role")
        payload_role = (payload or {}).get("role")
        role = detected or (_normalize_role(str(payload_role)) if payload_role else None)
        if not role:
            return

        # Benchmark hook: 최종 공개 인식 정확도. match=1 → 비전이 카드를 감지,
        # match=0 → 비전 미감지로 사용자가 직접 카드 선택.
        try:
            from benchmarks.common.trace_setup import bench_log
            bench_log().info("role_recognition reveal match=%d", 1 if detected else 0)
        except Exception:
            pass

        try:
            self._fsm.state.get_player(player_id).current_role = role
        except KeyError:
            return

        next_index = self._role_reveal["player_index"] + 1
        player_order = self._role_reveal["player_order"]

        if next_index < len(player_order):
            next_player = player_order[next_index]
            self._role_reveal["player_index"] = next_index
            self._role_reveal["player_id"] = next_player
            self._role_reveal["detected_role"] = None
            self._role_reveal["detected_low_confidence"] = False
            await self._push_role_reveal_context(next_player)
            await self._broadcast_role_reveal()
        else:
            self._role_reveal = None
            # FINAL_ROLE_REVEAL → RESULT (FSM이 judge_winner 계산 후 result 진입)
            await self.send_many(
                self._fsm.handle_input(WerewolfInputType.START_NOW, {}, None)
            )

    async def _push_role_reveal_context(self, player_id: str) -> None:
        self._state_version += 1
        # 최종 공개도 이 게임의 역할 풀(플레이어 카드 + 센터 카드)로만 인식 후보를 제한.
        in_game_roles: list[str] = []
        if self._fsm is not None:
            in_game_roles = sorted({
                _normalize_role(str(r)).lower()
                for r in (
                    [p.original_role for p in self._fsm.state.players]
                    + list(self._fsm.state.center_cards)
                )
            })
        ctx = FusionContext(
            fsm_state="final_role_reveal",
            game_type="werewolf_practice" if self._practice_mode else "werewolf",
            active_player=player_id,
            allowed_actors=[player_id],
            expected_events=[WerewolfEventType.ROLE_DETECTED],
            reject_events=[
                WerewolfEventType.CARD_PEEK,
                WerewolfEventType.CARD_SWAP,
                WerewolfEventType.VOTE_POINT,
            ],
            valid_targets=None,
            zones={},
            anchors={},
            params={"stabilization_frames": 1, "in_game_roles": in_game_roles},
        )
        self._send_fusion_context(ctx, self._state_version)

    async def _broadcast_role_reveal(self) -> None:
        if self._fsm is None:
            return
        self._state_version += 1
        all_roles = (
            [p.original_role for p in self._fsm.state.players]
            + list(self._fsm.state.center_cards)
        )
        payload = {
            **self._fsm.state.to_dict(),
            "phase": "final_role_reveal",
            "role_reveal": {**(self._role_reveal or {}), "all_roles": all_roles},
        }
        await self.send(WSMessage(
            msg_type=MsgType.STATE_UPDATE.value,
            payload=payload,
            state_version=self._state_version,
        ))

    async def _back_to_prev_player(self) -> None:
        """현재 플레이어의 이전 플레이어로 돌아간다. 이전 플레이어의 확정 역할을 취소."""
        if self._role_reg is None:
            return
        prev_index = self._role_reg["player_index"] - 1
        if prev_index < 0:
            return
        player_order = self._role_reg["player_order"]
        prev_player = player_order[prev_index]
        self._role_reg["confirmed_roles"].pop(prev_player, None)
        self._role_reg["player_index"] = prev_index
        self._role_reg["player_id"] = prev_player
        self._role_reg["detected_role"] = None
        self._role_reg["detected_low_confidence"] = False
        await self._push_role_reg_context(prev_player)
        await self._broadcast_role_reg()

    async def _back_to_card_setup(self) -> None:
        """role_registration 도중 카드 세팅 화면으로 되돌아간다. 확정된 역할은 초기화."""
        all_roles = list((self._role_reg or {}).get("all_roles", []))
        player_order = list((self._role_reg or {}).get("player_order", []))
        self._role_reg = None
        self._pending_role_reg = {
            "selected_roles": all_roles,
            "player_order": player_order,
        }
        # 웨어울프 파이프라인 유지 (card_setup OK 제스처도 웨어울프 FusionEngine이 처리)
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
            payload={"phase": "card_setup", "all_roles": all_roles},
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
        # 역할 등록 완료 후 게임 시작 경로 (기존 START_WEREWOLF_GAME 등)
        if self._pending_game_data is not None:
            data = self._pending_game_data
            self._pending_game_data = None
            await self._start_game(data)
            return
        # CardSetupGuide 완료 → 웨어울프 파이프라인으로 전환 후 역할 등록 시작
        if self._pending_role_reg is None:
            return
        data = self._pending_role_reg
        self._pending_role_reg = None
        selected_roles = data["selected_roles"]
        player_order = data["player_order"]
        first_player = player_order[0]
        self._role_reg = {
            "all_roles": selected_roles,
            "player_order": player_order,
            "player_index": 0,
            "player_id": first_player,
            "detected_role": None,
            "confirmed_roles": {},
        }
        await self._push_role_reg_context(first_player)
        await self._broadcast_role_reg()

    async def _broadcast_role_reg(self) -> None:
        self._state_version += 1
        await self.send(WSMessage(
            msg_type=MsgType.STATE_UPDATE.value,
            payload={"phase": "role_registration", "role_reg": dict(self._role_reg or {})},
            state_version=self._state_version,
        ))

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
            elif (
                msg.msg_type == MsgType.STATE_UPDATE.value
                and isinstance(msg.payload, dict)
                and msg.payload.get("phase") == "final_role_reveal"
            ):
                # FSM 상태 업데이트 대신 session이 role_reveal 포함 통합 상태를 브로드캐스트
                if self._role_reveal is None and self._fsm is not None:
                    await self._start_role_reveal()
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
        elif phase in ("day_discussion", "vote", "vote_countdown", "final_role_reveal"):
            target = "werewolf_day"
        else:
            # result, role_registration, card_setup 등 → 무음.
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
