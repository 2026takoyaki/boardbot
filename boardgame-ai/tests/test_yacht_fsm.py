from copy import deepcopy

from core.constants import MsgType
from core.events import GameEvent
from games.yacht import YachtEventType, YachtFSM, YachtInputType, YachtPhase


def _event(event_type: str, actor_id: str = "p1", dice=None) -> GameEvent:
    return GameEvent(
        event_type=event_type,
        actor_id=actor_id,
        confidence=0.95,
        frame_id=1,
        data={"dice_values": dice or [1, 2, 3, 4, 5], "keep_mask": [False] * 5},
    )


def _messages_of(msgs, msg_type):
    return [msg for msg in msgs if msg.msg_type == msg_type]


def test_start_sends_roll_context_for_first_player():
    fsm = YachtFSM(["p1", "p2"])

    msgs = fsm.start()
    ctx = _messages_of(msgs, MsgType.FUSION_CONTEXT.value)[0].payload

    assert fsm.state.phase == YachtPhase.AWAITING_ROLL.value
    assert ctx["fsm_state"] == YachtPhase.AWAITING_ROLL.value
    assert ctx["active_player"] == "p1"
    assert ctx["allowed_actors"] == ["p1"]
    assert YachtEventType.ROLL_CONFIRMED.value in ctx["expected_events"]
    assert YachtEventType.ROLL_UNREADABLE.value in ctx["expected_events"]
    # TTS는 FSM이 아닌 ProgressAgent가 last_message를 읽어 발화
    assert _messages_of(msgs, MsgType.TTS_PLAY.value) == []
    assert fsm.state.last_message == "p1님, 주사위를 굴려주세요."


def test_roll_confirmed_moves_to_keep_before_third_roll():
    fsm = YachtFSM(["p1"])
    fsm.start()

    msgs = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value))

    assert fsm.state.roll_count == 1
    assert fsm.state.dice_values == [1, 2, 3, 4, 5]
    assert fsm.state.phase == YachtPhase.AWAITING_KEEP.value
    assert _messages_of(msgs, MsgType.STATE_UPDATE.value)
    assert _messages_of(msgs, MsgType.TTS_PLAY.value) == []


def test_roll_confirmed_can_follow_previous_roll_without_reroll_request():
    fsm = YachtFSM(["p1"])
    fsm.start()

    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[1, 2, 3, 4, 5]))
    msgs = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[2, 2, 3, 4, 6]))
    ctx = _messages_of(msgs, MsgType.FUSION_CONTEXT.value)[0].payload

    assert fsm.state.roll_count == 2
    assert fsm.state.dice_values == [2, 2, 3, 4, 6]
    assert fsm.state.phase == YachtPhase.AWAITING_KEEP.value
    assert YachtEventType.ROLL_CONFIRMED.value in ctx["expected_events"]


def test_reroll_returns_to_awaiting_roll_with_same_player():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value))

    msgs = fsm.handle_input(
        YachtInputType.DICE_REROLL_REQUESTED.value,
        {"keep_mask": [True, False, False, False, True]},
        player_id="p1",
    )
    ctx = _messages_of(msgs, MsgType.FUSION_CONTEXT.value)[0].payload

    assert fsm.state.phase == YachtPhase.AWAITING_ROLL.value
    assert fsm.state.keep_mask == [True, False, False, False, True]
    assert ctx["active_player"] == "p1"


def test_third_roll_forces_score_phase():
    fsm = YachtFSM(["p1"])
    fsm.start()

    for _ in range(2):
        fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value))
        fsm.handle_input(YachtInputType.DICE_REROLL_REQUESTED.value, {}, player_id="p1")
    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value))

    assert fsm.state.roll_count == 3
    assert fsm.state.phase == YachtPhase.AWAITING_SCORE.value


def test_score_selection_records_score_and_advances_player():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[1, 1, 3, 4, 6]))

    msgs = fsm.handle_input(
        YachtInputType.SCORE_CATEGORY_SELECTED.value,
        {"category": "ones"},
        player_id="p1",
    )

    assert fsm.state.players[0].scores["ones"] == 2
    assert fsm.state.current_player.player_id == "p2"
    assert fsm.state.phase == YachtPhase.AWAITING_ROLL.value
    assert _messages_of(msgs, MsgType.FUSION_CONTEXT.value)[0].payload["active_player"] == "p2"
    # TTS는 FSM이 아닌 ProgressAgent가 last_message를 읽어 발화
    assert _messages_of(msgs, MsgType.TTS_PLAY.value) == []
    assert "에이스" in fsm.state.last_message
    assert "2점" in fsm.state.last_message


def test_turn_transition_emits_cue_with_structured_payload():
    """조명·모달이 last_message 문자열을 파싱하지 않아도 되게 하는 계약."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[1, 1, 3, 4, 6]))

    msgs = fsm.handle_input(
        YachtInputType.SCORE_CATEGORY_SELECTED.value,
        {"category": "ones"},
        player_id="p1",
    )
    cues = _messages_of(msgs, MsgType.CUE.value)

    assert len(cues) == 1
    payload = cues[0].payload
    assert payload["cue"] == "yacht_turn_transition"
    assert payload["scorer_id"] == "p1"
    assert payload["scorer_name"] == "p1"
    assert payload["category"] == "ones"
    assert payload["category_label"] == "에이스"
    assert payload["score"] == 2
    assert payload["is_highlight"] is False
    assert payload["next_player"] == "p2"
    # 모달·조명·TTS가 공유하는 타이밍. 없으면 세 채널이 어긋난다.
    assert payload["duration_ms"] > 0


def _score(fsm, category, player_id, dice=None, score=None):
    # actor_id를 맞춰줘야 차례 검증을 통과해 굴림이 기록된다.
    fsm.handle_event(
        _event(
            YachtEventType.ROLL_CONFIRMED.value,
            actor_id=player_id,
            dice=dice or [1, 2, 3, 4, 6],
        )
    )
    data = {"category": category}
    if score is not None:
        data["score"] = score
    return fsm.handle_input(
        YachtInputType.SCORE_CATEGORY_SELECTED.value, data, player_id=player_id
    )


def _cue_payload(msgs):
    return _messages_of(msgs, MsgType.CUE.value)[0].payload


def test_highlight_category_gets_longer_cue():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    payload = _cue_payload(_score(fsm, "yacht", "p1", dice=[5, 5, 5, 5, 5]))

    assert payload["variant"] == "highlight"
    assert payload["is_highlight"] is True
    assert payload["duration_ms"] > 2200


def test_scoring_zero_into_a_special_category_is_not_a_highlight():
    """요트 칸에 0점을 버리는 것은 축하가 아니라 그 반대다.

    족보를 '골랐다'가 아니라 '달성했다'여야 사건이다.
    """
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    payload = _cue_payload(_score(fsm, "yacht", "p1", dice=[1, 2, 3, 4, 6]))

    assert payload["score"] == 0
    assert payload["is_highlight"] is False
    assert payload["variant"] == "zero"


def test_zero_score_is_shortest_moment():
    """실패를 길게 보여줄 이유가 없다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    zero = _cue_payload(_score(fsm, "ones", "p1", dice=[2, 3, 4, 5, 6]))
    normal = _cue_payload(_score(fsm, "sixes", "p2", dice=[6, 6, 2, 3, 4]))

    assert zero["variant"] == "zero"
    assert normal["variant"] == "normal"
    assert zero["duration_ms"] < normal["duration_ms"]


def test_early_lead_swaps_are_not_treated_as_upsets():
    """초반에는 아무나 5점만 넣어도 1위다. 그걸 역전이라 하면 의미가 닳는다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    _score(fsm, "ones", "p1", dice=[1, 2, 3, 4, 6], score=1)
    payload = _cue_payload(_score(fsm, "sixes", "p2", dice=[6, 6, 6, 3, 4], score=18))

    assert payload["rank_before"] == 2
    assert payload["rank_after"] == 1
    assert payload["took_lead"] is False, "초반 순위 뒤집기는 사건이 아니다"
    assert payload["variant"] == "normal"


def test_late_game_lead_change_is_an_upset():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    # 두 사람 모두 후반부에 진입시키고, p1이 앞서 있게 만든다.
    for category in ("ones", "twos", "threes", "fours", "fives", "choice"):
        fsm.state.players[0].scores[category] = 10
        fsm.state.players[1].scores[category] = 1

    payload = _cue_payload(_score(fsm, "sixes", "p1", dice=[1, 2, 3, 4, 6], score=0))
    assert payload["variant"] == "zero"

    payload = _cue_payload(_score(fsm, "sixes", "p2", dice=[6, 6, 6, 6, 6], score=200))

    assert payload["took_lead"] is True
    assert payload["variant"] == "lead_change"
    assert payload["rank_before"] == 2
    assert payload["rank_after"] == 1
    assert payload["previous_leader"] == "p1"


def test_achieved_special_hand_outranks_a_simultaneous_lead_change():
    """야찌로 역전하면 야찌가 주인공이다. 더 드물고 더 상징적이다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    # p1 30점 선두, p2 6점. 야찌 50점이면 뒤집힌다.
    for category in ("ones", "twos", "threes", "fours", "fives", "choice"):
        fsm.state.players[0].scores[category] = 5
        fsm.state.players[1].scores[category] = 1

    _score(fsm, "sixes", "p1", dice=[1, 2, 3, 4, 6], score=0)
    payload = _cue_payload(_score(fsm, "yacht", "p2", dice=[5, 5, 5, 5, 5]))

    assert payload["took_lead"] is True
    assert payload["variant"] == "highlight"


def test_game_end_emits_finish_cue_without_next_player():
    fsm = YachtFSM(["p1"])
    fsm.start()
    # 마지막 한 칸만 남기고 채운다.
    for category in fsm.state.available_categories[:-1]:
        fsm.state.players[0].scores[category] = 0
    last_category = fsm.state.available_categories[0]
    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[1, 1, 3, 4, 6]))

    msgs = fsm.handle_input(
        YachtInputType.SCORE_CATEGORY_SELECTED.value,
        {"category": last_category},
        player_id="p1",
    )
    cues = _messages_of(msgs, MsgType.CUE.value)

    assert fsm.state.phase == YachtPhase.GAME_END.value
    assert len(cues) == 1
    assert cues[0].payload["cue"] == "yacht_game_finish"
    assert cues[0].payload["next_player"] is None


def test_restore_state_undoes_one_dice_roll():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    previous_state = deepcopy(fsm.state)

    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[1, 1, 3, 4, 6]))
    msgs = fsm.restore_state(previous_state, "p1님의 주사위 굴림을 되돌렸습니다.")
    ctx = _messages_of(msgs, MsgType.FUSION_CONTEXT.value)[0].payload

    assert "ones" not in fsm.state.players[0].scores
    assert fsm.state.current_player.player_id == "p1"
    assert fsm.state.roll_count == 0
    assert fsm.state.dice_values == []
    assert fsm.state.phase == YachtPhase.AWAITING_ROLL.value
    assert ctx["active_player"] == "p1"


def test_unreadable_roll_waits_for_manual_resolution():
    fsm = YachtFSM(["p1"])
    fsm.start()

    fsm.handle_event(
        GameEvent(
            event_type=YachtEventType.ROLL_UNREADABLE.value,
            actor_id="p1",
            confidence=0.6,
            frame_id=1,
            data={"dice_values": [1, None, 3, 4, None], "unknown_indices": [1, 4]},
        )
    )

    assert fsm.state.phase == YachtPhase.AWAITING_SCORE.value
    assert fsm.state.unreadable_roll["unknown_indices"] == [1, 4]


def test_wrong_turn_does_not_count_roll():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, actor_id="p2"))

    assert fsm.state.roll_count == 0
    assert fsm.state.phase == YachtPhase.AWAITING_ROLL.value
