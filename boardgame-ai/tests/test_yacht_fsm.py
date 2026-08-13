from copy import deepcopy

from core.constants import MsgType
from core.events import GameEvent
from games.yacht import YachtEventType, YachtFSM, YachtInputType, YachtPhase
from games.yacht.fsm import _CUE_DURATION_MS
from games.yacht.scoring import ALL_CATEGORIES


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
    # FSM은 문장을 만들지 않는다 — line_id와 데이터만 내보내고 문장 조립은
    # ProgressAgent(agents/tools/lines.py)가 한다. TTS도 FSM이 아닌 에이전트가 발화.
    assert _messages_of(msgs, MsgType.TTS_PLAY.value) == []
    assert fsm.state.narration == {
        "line_id": "yacht.turn_start",
        "params": {"player": "p1"},
    }


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
    # TTS는 FSM이 아닌 ProgressAgent가 narration을 렌더해 발화
    assert _messages_of(msgs, MsgType.TTS_PLAY.value) == []
    assert fsm.state.narration == {
        "line_id": "yacht.score_recorded",
        "params": {"scorer": "p1", "label": "에이스", "score": 2, "next": "p2"},
    }


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
    return fsm.handle_input(YachtInputType.SCORE_CATEGORY_SELECTED.value, data, player_id=player_id)


def _cue_payload(msgs):
    return _messages_of(msgs, MsgType.CUE.value)[0].payload


def test_confirming_a_special_hand_is_short_because_the_roll_already_celebrated():
    """굴림 순간에 크게 축하했으므로 확정은 점수만 못 박아주면 된다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    payload = _cue_payload(_score(fsm, "yacht", "p1", dice=[5, 5, 5, 5, 5]))

    assert payload["variant"] == "highlight"
    assert payload["is_highlight"] is True
    assert payload["duration_ms"] < _CUE_DURATION_MS["lead_change"]


def test_rolling_a_special_hand_celebrates_immediately():
    """축하는 칸을 고른 뒤가 아니라 주사위가 멈춘 순간에 터져야 한다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    msgs = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[5, 5, 5, 5, 5]))
    cues = _messages_of(msgs, MsgType.CUE.value)

    assert len(cues) == 1
    payload = cues[0].payload
    assert payload["cue"] == "yacht_hand_achieved"
    assert payload["category"] == "yacht"
    assert payload["category_label"] == "요트"
    assert payload["score"] == 50


def test_the_same_hand_celebrates_every_time_it_is_rolled():
    """세 번 굴릴 수 있고, 다시 맞춘 것도 그 나름의 순간이다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    first = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[5, 5, 5, 5, 5]))
    second = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[5, 5, 5, 5, 5]))

    assert _messages_of(first, MsgType.CUE.value)
    assert _messages_of(second, MsgType.CUE.value)


def test_ordinary_rolls_do_not_celebrate():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    msgs = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[1, 1, 3, 4, 6]))

    assert _messages_of(msgs, MsgType.CUE.value) == []


def test_celebration_falls_back_to_the_next_open_combination():
    """야찌 칸이 찼어도 그 눈은 여전히 포카드다. 넣을 수 있는 것을 축하한다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    fsm.state.players[0].scores["yacht"] = 0

    msgs = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[5, 5, 5, 5, 5]))
    payload = _cue_payload(msgs)

    assert payload["category"] == "four_of_a_kind"


def test_no_celebration_when_every_matching_category_is_used():
    """'요트!'라고 띄워놓고 넣을 곳이 없으면 축하가 아니라 약올리기다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    for category in ("yacht", "four_of_a_kind"):
        fsm.state.players[0].scores[category] = 0

    msgs = fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=[5, 5, 5, 5, 5]))

    assert _messages_of(msgs, MsgType.CUE.value) == []


def test_combination_tiers_scale_with_rarity():
    """다 똑같이 터뜨리면 야찌가 스몰 스트레이트와 같은 무게가 된다."""

    def tier_of(dice):
        fsm = YachtFSM(["p1", "p2"])
        fsm.start()
        return _cue_payload(
            fsm.handle_event(_event(YachtEventType.ROLL_CONFIRMED.value, dice=dice))
        )

    yacht = tier_of([5, 5, 5, 5, 5])
    large = tier_of([1, 2, 3, 4, 5])
    small = tier_of([1, 2, 3, 4, 4])

    assert yacht["tier"] == "legendary"
    assert large["tier"] == "epic"
    assert small["tier"] == "nice"
    assert yacht["duration_ms"] > large["duration_ms"] > small["duration_ms"]


def test_cue_payload_carries_every_field_the_ui_reads():
    """필드명이 어긋나면 조용히 연출만 안 나온다 — 에러도 로그도 없다.

    프론트 ScoreMoment/YachtGame이 읽는 키 목록. 이름을 바꾸려면 양쪽을 같이
    고쳐야 한다.
    """
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()

    payload = _cue_payload(_score(fsm, "ones", "p1", dice=[1, 1, 3, 4, 6]))

    consumed_by_ui = {
        "cue",
        "variant",
        "scorer_id",
        "scorer_name",
        "category",
        "category_label",
        "score",
        "took_lead",
        "rank_before",
        "rank_after",
        "previous_leader",
        "duration_ms",
    }

    assert consumed_by_ui <= set(payload)


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


def test_lead_change_outranks_a_special_hand_at_confirm_time():
    """조합은 주사위가 멈춘 순간에 이미 축하했다. 확정 시점의 주인공은 순위 변동이다."""
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    # p1 30점 선두, p2 6점. 야찌 50점이면 뒤집힌다.
    for category in ("ones", "twos", "threes", "fours", "fives", "choice"):
        fsm.state.players[0].scores[category] = 5
        fsm.state.players[1].scores[category] = 1

    _score(fsm, "sixes", "p1", dice=[1, 2, 3, 4, 6], score=0)
    payload = _cue_payload(_score(fsm, "yacht", "p2", dice=[5, 5, 5, 5, 5]))

    assert payload["took_lead"] is True
    assert payload["variant"] == "lead_change"


def test_climbing_without_taking_first_is_still_an_upset():
    """3등에서 2등도 역전이다. 1등 뺏기만 역전이라 하면 연출이 특정 플레이어에게만 붙는다."""
    fsm = YachtFSM(["p1", "p2", "p3"])
    fsm.start()
    filled = ("ones", "twos", "threes", "fours", "fives", "choice")
    for category in filled:
        fsm.state.players[0].scores[category] = 10  # 부동의 1위
        fsm.state.players[1].scores[category] = 4  # 2위
        fsm.state.players[2].scores[category] = 3  # 3위

    _score(fsm, "sixes", "p1", dice=[1, 2, 3, 4, 6], score=0)
    _score(fsm, "sixes", "p2", dice=[1, 2, 3, 4, 6], score=0)
    # p3가 2위는 제치되 1위에는 못 미치는 점수.
    payload = _cue_payload(_score(fsm, "sixes", "p3", dice=[6, 6, 2, 3, 4], score=12))

    assert payload["rank_before"] == 3
    assert payload["rank_after"] == 2
    assert payload["overtook"] is True
    assert payload["took_lead"] is False
    assert payload["variant"] == "lead_change"


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


def test_turn_skips_players_whose_scorecard_is_full():
    """고를 칸이 없는 사람에게 차례가 가면 게임이 멈춘다.

    종료 조건이 "전원이 다 채웠는가"라, 한 명만 먼저 다 채운 상태에서 그 사람에게
    차례가 돌아오면 점수를 넣을 수도 게임을 끝낼 수도 없다. 정상 플레이에서는
    칸 수가 어긋나지 않지만 되돌리기·상태 복원이 그 전제를 깰 수 있다.
    """
    fsm = YachtFSM(["p1", "p2", "p3"])
    fsm.start()
    everything = [category.value for category in ALL_CATEGORIES]
    # p2만 점수판을 다 채운 상태.
    for category in everything:
        fsm.state.players[1].scores[category] = 1

    fsm.state.current_player_index = 0
    fsm.state.advance_player()

    assert fsm.state.current_player.player_id == "p3", "다 채운 p2를 건너뛰어야 한다"
    assert fsm.state.available_categories, "차례를 받은 사람은 고를 칸이 있어야 한다"


def test_game_ends_instead_of_deadlocking_when_counts_are_uneven():
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    everything = [category.value for category in ALL_CATEGORIES]
    for category in everything:
        fsm.state.players[0].scores[category] = 1
    for category in everything[:-1]:
        fsm.state.players[1].scores[category] = 1

    fsm.state.current_player_index = 0
    fsm.state.advance_player()
    assert fsm.state.current_player.player_id == "p2"

    msgs = _score(fsm, everything[-1], "p2", dice=[1, 1, 3, 4, 6])

    assert fsm.state.phase == YachtPhase.GAME_END.value
    assert _messages_of(msgs, MsgType.CUE.value)[0].payload["cue"] == "yacht_game_finish"


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
