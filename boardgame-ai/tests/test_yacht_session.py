from __future__ import annotations

import pytest

from backend.yacht_session import YachtSession
from core.events import GameEvent
from games.yacht import YachtEventType


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _latest_state(ws: FakeWebSocket) -> dict:
    return [msg for msg in ws.sent if msg["msg_type"] == "state_update"][-1]["payload"]


@pytest.mark.anyio
async def test_yacht_session_undo_restores_last_dice_roll_only():
    ws = FakeWebSocket()
    session = YachtSession(ws)

    await session.start_game(
        {
            "players": [
                {"player_id": "p1", "playername": "p1"},
                {"player_id": "p2", "playername": "p2"},
            ]
        }
    )
    await session.handle_client_message(
        {"input_type": "ROLL_DICE", "data": {"dice_values": [1, 1, 3, 4, 6]}}
    )

    rolled = _latest_state(ws)
    assert rolled["roll_count"] == 1
    assert rolled["dice_values"] == [1, 1, 3, 4, 6]
    assert rolled["can_undo"] is True

    await session.handle_client_message({"input_type": "UNDO_ROUND", "data": {}})

    undone = _latest_state(ws)
    assert undone["current_player_id"] == "p1"
    assert undone["roll_count"] == 0
    assert undone["dice_values"] == []
    assert undone["phase"] == "AWAITING_ROLL"
    assert undone["can_undo"] is False


@pytest.mark.anyio
async def test_yacht_session_score_selection_clears_dice_undo_history():
    ws = FakeWebSocket()
    session = YachtSession(ws)

    await session.start_game(
        {
            "players": [
                {"player_id": "p1", "playername": "p1"},
                {"player_id": "p2", "playername": "p2"},
            ]
        }
    )
    await session.handle_client_message(
        {"input_type": "ROLL_DICE", "data": {"dice_values": [1, 1, 3, 4, 6]}}
    )
    await session.handle_client_message(
        {
            "input_type": "SCORE_CATEGORY_SELECTED",
            "player_id": "p1",
            "data": {"category": "ones"},
        }
    )

    scored = _latest_state(ws)
    assert scored["current_player_id"] == "p2"
    assert scored["players"][0]["scores"] == {"ones": 2}
    assert scored["can_undo"] is False


@pytest.mark.anyio
async def test_manual_dice_input_after_unreadable_roll_counts_as_roll():
    """인식 실패(ROLL_UNREADABLE) 후 수동 입력은 정식 굴림 1회로 카운트되고
    AWAITING_KEEP으로 복귀해 남은 굴림 기회를 보존해야 한다.

    이전에는 AWAITING_SCORE에 머물러 굴림 기회가 사라지고, 비전이
    ROLL_CONFIRMED를 거부하는 단계라 다시 굴려도 인식되지 않았다.
    """
    ws = FakeWebSocket()
    session = YachtSession(ws)

    await session.start_game({"players": [{"player_id": "p1", "playername": "p1"}]})

    # 첫 굴림이 일부 인식 실패 → AWAITING_SCORE로 강제 진입, 굴림 미카운트.
    await session.dispatch_vision_event(
        GameEvent(
            event_type=YachtEventType.ROLL_UNREADABLE.value,
            actor_id="p1",
            confidence=0.6,
            frame_id=1,
            data={"dice_values": [1, None, 3, 4, None], "unknown_indices": [1, 4]},
        )
    )
    unreadable = _latest_state(ws)
    assert unreadable["phase"] == "AWAITING_SCORE"
    assert unreadable["roll_count"] == 0

    # 수동 입력으로 눈을 확정 → 굴림 1회 카운트 + AWAITING_KEEP 복귀.
    await session.handle_client_message(
        {"input_type": "MANUAL_DICE_INPUT", "data": {"dice_values": [1, 2, 3, 4, 5]}}
    )
    resolved = _latest_state(ws)
    assert resolved["phase"] == "AWAITING_KEEP"
    assert resolved["roll_count"] == 1
    assert resolved["remaining_rolls"] == 2
    assert resolved["dice_values"] == [1, 2, 3, 4, 5]
    assert resolved["unreadable_roll"] is None
    assert resolved["can_undo"] is True


@pytest.mark.anyio
async def test_manual_dice_input_in_awaiting_keep_only_corrects_values():
    """정상 인식 후(AWAITING_KEEP) 수동 입력은 눈만 정정하고 굴림은 카운트하지 않는다."""
    ws = FakeWebSocket()
    session = YachtSession(ws)

    await session.start_game({"players": [{"player_id": "p1", "playername": "p1"}]})
    await session.handle_client_message(
        {"input_type": "ROLL_DICE", "data": {"dice_values": [1, 1, 3, 4, 6]}}
    )
    assert _latest_state(ws)["roll_count"] == 1

    await session.handle_client_message(
        {"input_type": "MANUAL_DICE_INPUT", "data": {"dice_values": [2, 2, 3, 4, 6]}}
    )
    corrected = _latest_state(ws)
    assert corrected["phase"] == "AWAITING_KEEP"
    assert corrected["roll_count"] == 1
    assert corrected["dice_values"] == [2, 2, 3, 4, 6]


@pytest.mark.anyio
async def test_yacht_tutorial_mode_accepts_vision_rolls():
    ws = FakeWebSocket()
    session = YachtSession(ws)

    await session.start_game(
        {
            "tutorial_mode": True,
            "players": [{"player_id": "p1", "playername": "p1"}],
        }
    )

    started = _latest_state(ws)
    assert started["tutorial_mode"] is True

    await session.dispatch_vision_event(
        GameEvent(
            event_type=YachtEventType.ROLL_CONFIRMED.value,
            actor_id="p1",
            confidence=0.95,
            frame_id=10,
            data={"dice_values": [1, 2, 3, 4, 5], "keep_mask": [False] * 5},
        )
    )

    after_vision = _latest_state(ws)
    assert after_vision["roll_count"] == 1
    assert after_vision["dice_values"] == [1, 2, 3, 4, 5]
    assert after_vision["tutorial_mode"] is True


@pytest.mark.anyio
async def test_yacht_tutorial_mode_finishes_after_each_player_scores_once():
    ws = FakeWebSocket()
    session = YachtSession(ws)

    await session.start_game(
        {
            "tutorial_mode": True,
            "players": [
                {"player_id": "p1", "playername": "p1"},
                {"player_id": "p2", "playername": "p2"},
            ],
        }
    )

    await session.handle_client_message(
        {"input_type": "ROLL_DICE", "data": {"dice_values": [1, 1, 3, 4, 6]}}
    )
    await session.handle_client_message(
        {
            "input_type": "SCORE_CATEGORY_SELECTED",
            "player_id": "p1",
            "data": {"category": "ones"},
        }
    )

    after_p1 = _latest_state(ws)
    assert after_p1["tutorial_complete"] is False
    assert after_p1["current_player_id"] == "p2"

    await session.handle_client_message(
        {"input_type": "ROLL_DICE", "data": {"dice_values": [2, 2, 3, 4, 6]}}
    )
    await session.handle_client_message(
        {
            "input_type": "SCORE_CATEGORY_SELECTED",
            "player_id": "p2",
            "data": {"category": "twos"},
        }
    )

    completed = _latest_state(ws)
    assert completed["tutorial_complete"] is True
    assert completed["players"][0]["scores"] == {"ones": 2}
    assert completed["players"][1]["scores"] == {"twos": 4}


@pytest.mark.anyio
async def test_화면_상태줄이_narration에서_렌더된다():
    """FSM은 line_id만 내보내므로, 백엔드가 문장으로 만들어주지 않으면
    화면 상태줄이 통째로 빈칸이 된다. 음성과 같은 카탈로그를 쓰는지도 함께 본다."""
    ws = FakeWebSocket()
    session = YachtSession(ws)

    await session.start_game(
        {
            "players": [
                {"player_id": "p1", "playername": "성민"},
                {"player_id": "p2", "playername": "형승"},
            ]
        }
    )

    started = _latest_state(ws)
    assert started["narration"] == {
        "line_id": "yacht.turn_start",
        "params": {"player": "성민"},
    }
    assert started["last_message"] == "성민님, 주사위를 굴려주세요."

    await session.handle_client_message(
        {"input_type": "ROLL_DICE", "data": {"dice_values": [1, 1, 3, 4, 6]}}
    )

    rolled = _latest_state(ws)
    assert rolled["narration"]["line_id"] == "yacht.roll_partial"
    assert rolled["last_message"] == "기회 두 번 남았습니다. 다시 굴리거나 점수 칸을 선택해주세요."
