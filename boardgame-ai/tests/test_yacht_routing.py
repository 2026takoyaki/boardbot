"""yacht_runner 라우팅 + FSM FUSION_CONTEXT 메시지 검증.

실제 LocalBridge를 사용해 비전 발화 → 활성 YachtSession 라우팅 흐름을 검증.
WebSocket은 FakeWebSocket으로 대체.

asyncio loop은 별도 스레드에서 돌려서 yacht_runner._route_event의
run_coroutine_threadsafe가 정상 동작하도록 한다.

대기는 time.sleep 대신 threading.Event 기반 deterministic polling으로
처리해 CI/느린 머신 플래키 방지.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

import pytest

from backend.server import YachtSession
from backend.yacht_runner import YachtRunner
from bridge.local_bridge import LocalBridge
from core.constants import CommonEventType, MsgType
from core.events import FusionContext, GameEvent
from games.yacht import YachtEventType, YachtFSM
from vision.yacht.config import VisionConfig

# ── FakeWebSocket ───────────────────────────────────────────────────────────


class FakeWebSocket:
    """WebSocket 인터페이스 중 send_json만 구현. 송신 메시지 기록 + Event 알림.

    `wait_for(msg_type, timeout)`로 특정 msg_type 도착을 deterministic 하게 대기 가능.
    """

    def __init__(self) -> None:
        self.sent: list[dict] = []
        self._cond = threading.Condition()

    async def send_json(self, payload: dict) -> None:
        with self._cond:
            self.sent.append(payload)
            self._cond.notify_all()

    def wait_for(self, msg_type: str, timeout: float = 2.0, after: int = 0) -> bool:
        """`after` 인덱스 이후에 해당 msg_type이 도착할 때까지 대기.

        `after`는 sent 리스트의 시작 인덱스. 보통 호출 직전의 len(self.sent).
        그 이후 새로 도착한 메시지에서만 매칭. True면 도착, False면 timeout.
        """

        def _arrived() -> bool:
            return any(m.get("msg_type") == msg_type for m in self.sent[after:])

        with self._cond:
            return self._cond.wait_for(_arrived, timeout=timeout)

    def wait_quiet(self, timeout: float = 0.05) -> None:
        """짧은 시간 안에 새 메시지가 안 오는 것을 확인 (음성 검증)."""
        snapshot = len(self.sent)
        with self._cond:
            self._cond.wait_for(lambda: len(self.sent) > snapshot, timeout=timeout)


def _make_event(event_type: str, actor_id: str = "p1", **data: Any) -> GameEvent:
    return GameEvent(
        event_type=event_type,
        actor_id=actor_id,
        confidence=0.95,
        frame_id=1,
        data=data,
    )


@pytest.fixture()
def loop_in_thread():
    """asyncio loop을 별도 스레드에서 돌리는 fixture.

    started_event로 loop 진입을 동기화, set_event_loop로 스레드 컨텍스트에
    loop을 등록해 일부 asyncio API가 current loop을 찾을 수 있게 한다.
    """
    loop = asyncio.new_event_loop()
    started = threading.Event()

    def _run() -> None:
        asyncio.set_event_loop(loop)
        loop.call_soon(started.set)
        loop.run_forever()

    thread = threading.Thread(target=_run, daemon=True, name="test-loop")
    thread.start()
    assert started.wait(timeout=2.0), "test loop failed to start"
    try:
        yield loop
    finally:
        loop.call_soon_threadsafe(loop.stop)
        thread.join(timeout=2.0)
        assert not thread.is_alive(), "test loop thread did not exit"
        loop.close()


def _start_session_sync(session: YachtSession, loop: asyncio.AbstractEventLoop) -> None:
    """async start_game을 동기로 실행 (해당 loop에서)."""
    fut = asyncio.run_coroutine_threadsafe(
        session.start_game({"players": [{"player_id": "p1", "playername": "A"}]}),
        loop,
    )
    fut.result(timeout=2.0)


# ── YachtRunner 라우팅 ──────────────────────────────────────────────────────


def test_yacht_event_routes_to_active_session(loop_in_thread) -> None:
    """ROLL_CONFIRMED 발화 → 활성 session.dispatch_vision_event 호출.

    STATE_UPDATE는 클라이언트(ws)로, FUSION_CONTEXT는 브리지(비전)로 라우팅된다.
    """
    bridge = LocalBridge()
    runner = YachtRunner(config=VisionConfig(), bridge=bridge, loop=loop_in_thread)

    ws = FakeWebSocket()
    session = YachtSession(websocket=ws, bridge=bridge)

    # FUSION_CONTEXT는 ws가 아니라 bridge로 전달되므로 bridge 쪽에서 수신 대기.
    ctx_received = threading.Event()
    received_states: list[str] = []

    def _capture_ctx(ctx: FusionContext, _version: int) -> None:
        received_states.append(ctx.fsm_state)
        ctx_received.set()

    bridge.on_fusion_context(_capture_ctx)

    _start_session_sync(session, loop_in_thread)
    runner.register_session(session)

    sent_before = len(ws.sent)
    ctx_received.clear()  # start_game이 보낸 초기 context는 제외

    event = _make_event(
        YachtEventType.ROLL_CONFIRMED.value,
        dice_values=[1, 2, 3, 4, 5],
        keep_mask=[False] * 5,
    )
    bridge.send_game_event(event, state_version=2)

    # FSM 응답이 도착할 때까지 deterministic 대기 (start_game 메시지 이후만)
    assert ws.wait_for(MsgType.STATE_UPDATE.value, timeout=2.0, after=sent_before)
    assert ctx_received.wait(timeout=2.0), "FUSION_CONTEXT가 bridge로 전달되지 않음"
    assert received_states[-1] in ("AWAITING_KEEP", "AWAITING_SCORE")


def test_yacht_event_ignored_when_no_active_session(loop_in_thread) -> None:
    """활성 세션 없을 때 ROLL_CONFIRMED 도착 → 예외 없이 무시."""
    bridge = LocalBridge()
    YachtRunner(config=VisionConfig(), bridge=bridge, loop=loop_in_thread)  # register 안 함

    event = _make_event(YachtEventType.ROLL_CONFIRMED.value, dice_values=[1] * 5)
    # 예외만 안 뜨면 OK
    bridge.send_game_event(event, state_version=1)


def test_non_yacht_event_not_routed_to_yacht(loop_in_thread) -> None:
    """SEAT_REGISTERED 같은 비-yacht 이벤트는 yacht runner가 무시해야 함."""
    bridge = LocalBridge()
    runner = YachtRunner(config=VisionConfig(), bridge=bridge, loop=loop_in_thread)

    ws = FakeWebSocket()
    session = YachtSession(websocket=ws, bridge=bridge)
    _start_session_sync(session, loop_in_thread)
    runner.register_session(session)

    sent_before = len(ws.sent)
    event = _make_event(CommonEventType.SEAT_REGISTERED.value)
    bridge.send_game_event(event, state_version=1)

    # 짧은 시간 동안 추가 메시지가 도착하지 않는지 확인
    ws.wait_quiet(timeout=0.1)
    assert len(ws.sent) == sent_before


# ── FSM on_fusion_context 콜백 ──────────────────────────────────────────────


def test_fusion_context_published_on_start() -> None:
    """FSM.start() 호출 시 FUSION_CONTEXT WSMessage 반환. 브리지 호출은 세션 담당."""
    fsm = YachtFSM([{"player_id": "p1", "playername": "A"}])
    messages = fsm.start()

    fusion_msgs = [m for m in messages if m.msg_type == MsgType.FUSION_CONTEXT.value]
    assert len(fusion_msgs) == 1
    ctx = FusionContext.from_dict(fusion_msgs[0].payload)
    assert ctx.game_type == "yacht"
    assert ctx.fsm_state == "AWAITING_ROLL"
    assert fusion_msgs[0].state_version == fsm.state.state_version


def test_fusion_context_published_after_roll_confirmed() -> None:
    """ROLL_CONFIRMED 처리 후 FUSION_CONTEXT 메시지 반환 (AWAITING_KEEP or AWAITING_SCORE)."""
    fsm = YachtFSM([{"player_id": "p1", "playername": "A"}])
    fsm.start()

    event = _make_event(
        YachtEventType.ROLL_CONFIRMED.value,
        dice_values=[1, 2, 3, 4, 5],
        keep_mask=[False] * 5,
    )
    messages = fsm.handle_event(event)

    fusion_msgs = [m for m in messages if m.msg_type == MsgType.FUSION_CONTEXT.value]
    assert fusion_msgs
    ctx = FusionContext.from_dict(fusion_msgs[-1].payload)
    assert ctx.fsm_state in ("AWAITING_KEEP", "AWAITING_SCORE")


# ── deregister race condition ───────────────────────────────────────────────


def test_deregister_only_clears_matching_session(loop_in_thread) -> None:
    """빠른 재연결 시 새 세션을 옛 세션의 deregister가 덮어쓰지 않아야."""
    bridge = LocalBridge()
    runner = YachtRunner(config=VisionConfig(), bridge=bridge, loop=loop_in_thread)

    ws = FakeWebSocket()
    old_session = YachtSession(websocket=ws, bridge=bridge)
    new_session = YachtSession(websocket=ws, bridge=bridge)

    runner.register_session(old_session)
    runner.register_session(new_session)
    runner.deregister_session(old_session)

    assert runner._active_session is new_session
