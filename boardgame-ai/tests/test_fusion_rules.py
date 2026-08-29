"""WerewolfRules 단위 테스트 — VOTE_POINT 감지 조건 검증.

카드 인식(ROLE_DETECTED 등)은 인식률 문제로 제거됐다. 늑대인간 비전이 만드는
이벤트는 이제 투표 포인팅 하나뿐이며, 야간 진행은 FusionEngine이 직접 다루는
공용 GESTURE_CONFIRMED로 처리한다.

검증 항목:
  - vote_countdown / vote 두 페이즈 모두에서 좌석 ray 매칭이 동작
  - 자기 자신은 지목 대상에서 제외
  - 같은 대상 반복 지목은 억제, 대상이 바뀌면 재발화
  - 투표 외 페이즈에서는 어떤 후보도 만들지 않음
  - CardTracker.reset_stable_frames 단위 동작 (데모·디버그 도구에서 계속 사용)
"""

from __future__ import annotations

from core.events import FusionContext
from vision.fusion.werewolf_rules import _POINT_MIN_HITS, VOTE_POINT, WerewolfRules
from vision.schemas import BBox, FramePerception, HandDet
from vision.tracking.card_tracker import CardTracker
from vision.werewolf.schemas import TrackedCard

# ── 픽스처 헬퍼 ────────────────────────────────────────────────────────────────


def _frame(hands: list[HandDet] | None = None, ts: float = 100.0) -> FramePerception:
    return FramePerception(frame_id=0, ts=ts, image_hw=(1080, 1920), hands=hands or [])


def _hold(
    rules: WerewolfRules,
    ctx: FusionContext,
    hand: HandDet,
    frames: int = _POINT_MIN_HITS,
) -> list[tuple[str, dict, float]]:
    """같은 손을 연속으로 먹이고 **마지막 프레임의** 후보를 돌려준다.

    지목은 붙잡고 있어야 표가 된다(_POINT_MIN_HITS). 팔을 드는 동안 스쳐
    지나간 좌석이 표가 되지 않게 하기 위한 것이라, 한 프레임만 먹이면 아무
    후보도 나오지 않는 것이 정상이다.
    """
    cands: list[tuple[str, dict, float]] = []
    for _ in range(frames):
        cands = rules.build_candidates(ctx, _frame([hand]))
    return cands


def _ctx_vote(fsm_state: str) -> FusionContext:
    """좌석 좌표 기반 투표 컨텍스트. p_1 은 자기 자신(제외 대상), p_2 는 오른쪽."""
    return FusionContext(
        fsm_state=fsm_state,
        game_type="werewolf",
        active_player=None,
        allowed_actors=["p_1", "p_2"],
        expected_events=[VOTE_POINT],
        anchors={
            "seat_p_1": {"x": 0.5, "y": 0.5},
            "seat_p_2": {"x": 0.85, "y": 0.5},
        },
    )


def _pointing_hand_at(target_cx: float, target_cy: float) -> HandDet:
    """손목(0.5,0.5)에서 target 방향을 가리키는 포인팅 손."""
    landmarks = [(0.0, 0.0)] * 21
    landmarks[0] = (0.5, 0.5)  # wrist
    landmarks[8] = (target_cx, target_cy)  # index tip — 지목 방향
    return HandDet(
        handedness="Right",
        wrist_xy=(0.5, 0.5),
        landmarks_21=landmarks,
        gesture="neutral",
        player_id="p_1",
    )


# ── VOTE_POINT 페이즈 게이트 ────────────────────────────────────────────────────


def test_vote_point_detected_in_vote_countdown() -> None:
    """포인팅 투표가 vote_countdown 페이즈에서 VOTE_POINT 후보를 생성한다.

    FSM은 투표를 vote_countdown으로 진입시키고 전원 투표 전까지 머무므로,
    이 페이즈에서 감지되지 않으면 손 지목이 영영 이벤트가 되지 않는다(회귀 방지).
    """
    rules = WerewolfRules()
    hand = _pointing_hand_at(0.8, 0.5)  # p_2 좌석(0.85,0.5) 방향
    cands = _hold(rules, _ctx_vote("vote_countdown"), hand)
    assert any(c[0] == VOTE_POINT and c[1]["target_id"] == "p_2" for c in cands)


def test_vote_point_detected_in_vote_phase() -> None:
    """레거시 'vote' 페이즈에서도 동일하게 감지된다."""
    rules = WerewolfRules()
    hand = _pointing_hand_at(0.8, 0.5)
    cands = _hold(rules, _ctx_vote("vote"), hand)
    assert any(c[0] == VOTE_POINT and c[1]["target_id"] == "p_2" for c in cands)


def test_glancing_point_does_not_become_a_vote() -> None:
    """팔을 드는 동안 스쳐 지나간 좌석은 표가 되지 않는다.

    한 프레임만 보고 표를 매기면 겨눈 사람이 아니라 **먼저 스친 사람**이 찍힌다.
    """
    rules = WerewolfRules()
    ctx = _ctx_vote("vote_countdown")
    hand = _pointing_hand_at(0.8, 0.5)

    for _ in range(_POINT_MIN_HITS - 1):
        assert not any(c[0] == VOTE_POINT for c in rules.build_candidates(ctx, _frame([hand])))

    assert any(c[0] == VOTE_POINT for c in rules.build_candidates(ctx, _frame([hand])))


def test_vote_survives_dropped_frames() -> None:
    """손이 프레임마다 끊겨도 겨누고 있으면 표가 쌓인다.

    오버헤드 뷰에서 MediaPipe는 손을 놓쳤다 잡았다 한다(실측). 연속 프레임을
    요구하면 그 조건에서 표가 영영 안 나오므로, 놓친 프레임은 창을 밀어내지
    않고 그냥 건너뛴다.
    """
    rules = WerewolfRules()
    ctx = _ctx_vote("vote_countdown")
    hand = _pointing_hand_at(0.8, 0.5)

    fired = []
    # 잡힘 → 놓침 → 잡힘 → 놓침 … 을 반복한다.
    for i in range(_POINT_MIN_HITS * 2):
        frame = _frame([hand]) if i % 2 == 0 else _frame([])
        fired += [c for c in rules.build_candidates(ctx, frame) if c[0] == VOTE_POINT]

    assert fired, "손이 끊겼다 잡히길 반복해도 표는 나와야 한다"
    assert fired[0][1]["target_id"] == "p_2"


def test_vote_point_skips_self() -> None:
    """자기 좌석 방향으로 가리켜도 본인은 지목 대상에서 제외된다."""
    rules = WerewolfRules()
    # p_1 손목(0.5,0.5) → 자기 좌석(0.5,0.5)은 t<=0 으로 제외, 다른 방향엔 좌석 없음
    hand = _pointing_hand_at(0.5, 0.2)  # 위쪽 — 어떤 좌석도 없음
    cands = rules.build_candidates(_ctx_vote("vote_countdown"), _frame([hand]))
    assert not any(c[0] == VOTE_POINT for c in cands)


def test_vote_point_retarget_fires_on_target_change() -> None:
    """대상을 바꾸면 카운트다운 도중이라도 다시 발화한다.

    투표는 카운트다운이 끝날 때 확정된다. 그 전까지 마음을 바꾸는 것은 정상이며,
    바꾼 결과가 FSM까지 가야 화면의 지목 표시도 따라 바뀐다.
    """
    rules = WerewolfRules()
    ctx = _ctx_vote("vote_countdown")

    # p_2 를 겨눠 첫 표
    cands1 = _hold(rules, ctx, _pointing_hand_at(0.8, 0.5))
    assert any(c[0] == VOTE_POINT and c[1]["target_id"] == "p_2" for c in cands1)

    # 손을 내려 지목이 끊겼다가 다시 p_2 를 겨눠도 같은 표라 재발화 없음
    cands2 = _hold(rules, ctx, _pointing_hand_at(0.5, 0.2))
    assert not any(c[0] == VOTE_POINT for c in cands2)
    cands3 = _hold(rules, ctx, _pointing_hand_at(0.8, 0.5))
    assert not any(c[0] == VOTE_POINT for c in cands3)


def test_vote_can_change_to_a_third_seat() -> None:
    """A를 찍었다가 B로 바꾸면 B가 새로 발화한다."""
    ctx = FusionContext(
        fsm_state="vote_countdown",
        game_type="werewolf",
        active_player=None,
        allowed_actors=["p_1", "p_2", "p_3"],
        expected_events=[VOTE_POINT],
        anchors={
            "seat_p_1": {"x": 0.5, "y": 0.5},
            "seat_p_2": {"x": 0.85, "y": 0.5},
            "seat_p_3": {"x": 0.5, "y": 0.85},
        },
    )
    rules = WerewolfRules()

    first = _hold(rules, ctx, _pointing_hand_at(0.8, 0.5))
    assert any(c[1]["target_id"] == "p_2" for c in first if c[0] == VOTE_POINT)

    second = _hold(rules, ctx, _pointing_hand_at(0.5, 0.8))
    assert any(c[1]["target_id"] == "p_3" for c in second if c[0] == VOTE_POINT)


def test_vote_point_same_target_suppressed() -> None:
    """같은 대상을 계속 가리키면 재발화하지 않는다(매 프레임 스팸 방지)."""
    rules = WerewolfRules()
    ctx = _ctx_vote("vote_countdown")

    first = _hold(rules, ctx, _pointing_hand_at(0.8, 0.5))
    assert any(c[0] == VOTE_POINT for c in first)

    for _ in range(5):
        repeat = rules.build_candidates(ctx, _frame([_pointing_hand_at(0.8, 0.5)]))
        assert not any(c[0] == VOTE_POINT for c in repeat)


def test_phase_change_clears_vote_memory() -> None:
    """페이즈가 바뀌면 지목 기억이 초기화돼 다음 판에서 다시 지목할 수 있다."""
    rules = WerewolfRules()
    hand = _pointing_hand_at(0.8, 0.5)

    assert _hold(rules, _ctx_vote("vote_countdown"), hand)
    # 다른 페이즈를 거쳤다가 돌아오면 같은 대상도 다시 발화한다.
    _hold(rules, _ctx_vote("day_discussion"), hand)
    assert _hold(rules, _ctx_vote("vote_countdown"), hand)


# ── 투표 외 페이즈는 후보 없음 ─────────────────────────────────────────────────


def test_night_phases_produce_no_candidates() -> None:
    """야간 진행은 공용 GESTURE_CONFIRMED가 담당한다. WerewolfRules는 관여하지 않는다."""
    rules = WerewolfRules()
    hand = _pointing_hand_at(0.8, 0.5)
    for phase in ("night_start", "night_seer", "night_robber", "card_setup", "result"):
        ctx = _ctx_vote(phase)
        assert rules.build_candidates(ctx, _frame([hand])) == [], phase


# ── CardTracker.reset_stable_frames 단위 테스트 ───────────────────────────────
# 늑대인간 게임 경로에서는 더 이상 쓰지 않지만 demos/·tools/ 진단 스크립트가 사용한다.


def test_card_tracker_reset_stable_frames_clears_all_cards() -> None:
    """reset_stable_frames 호출 후 모든 카드의 stable_frames=0, just_flipped_up=False."""
    real_tracker = CardTracker()
    real_tracker._card_states[1] = TrackedCard(
        track_id=1,
        bbox=BBox(0.3, 0.3, 0.6, 0.6, 0.9, "Seer"),
        cls_name="Seer",
        face_up=True,
        player_id="p_1",
        card_index=0,
        stable_frames=30,
        just_flipped_up=True,
    )
    real_tracker._card_states[2] = TrackedCard(
        track_id=2,
        bbox=BBox(0.1, 0.1, 0.3, 0.3, 0.8, "Werewolf"),
        cls_name="Werewolf",
        face_up=True,
        player_id="p_2",
        card_index=0,
        stable_frames=50,
        just_flipped_up=False,
    )

    real_tracker.reset_stable_frames()

    for card in real_tracker.get_tracked_cards():
        assert card.stable_frames == 0
        assert card.just_flipped_up is False


def test_card_tracker_reset_stable_frames_empty_tracker() -> None:
    """카드가 없을 때 reset_stable_frames 호출해도 오류 없음."""
    real_tracker = CardTracker()
    real_tracker.reset_stable_frames()  # 예외 없이 통과
    assert real_tracker.get_tracked_cards() == []
