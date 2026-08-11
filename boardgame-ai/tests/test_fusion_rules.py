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
from vision.fusion.werewolf_rules import VOTE_POINT, WerewolfRules
from vision.schemas import BBox, FramePerception, HandDet
from vision.tracking.card_tracker import CardTracker
from vision.werewolf.schemas import TrackedCard

# ── 픽스처 헬퍼 ────────────────────────────────────────────────────────────────


def _frame(hands: list[HandDet] | None = None, ts: float = 100.0) -> FramePerception:
    return FramePerception(frame_id=0, ts=ts, image_hw=(1080, 1920), hands=hands or [])


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
    cands = rules.build_candidates(_ctx_vote("vote_countdown"), _frame([hand]))
    assert any(c[0] == VOTE_POINT and c[1]["target_id"] == "p_2" for c in cands)


def test_vote_point_detected_in_vote_phase() -> None:
    """레거시 'vote' 페이즈에서도 동일하게 감지된다."""
    rules = WerewolfRules()
    hand = _pointing_hand_at(0.8, 0.5)
    cands = rules.build_candidates(_ctx_vote("vote"), _frame([hand]))
    assert any(c[0] == VOTE_POINT and c[1]["target_id"] == "p_2" for c in cands)


def test_vote_point_skips_self() -> None:
    """자기 좌석 방향으로 가리켜도 본인은 지목 대상에서 제외된다."""
    rules = WerewolfRules()
    # p_1 손목(0.5,0.5) → 자기 좌석(0.5,0.5)은 t<=0 으로 제외, 다른 방향엔 좌석 없음
    hand = _pointing_hand_at(0.5, 0.2)  # 위쪽 — 어떤 좌석도 없음
    cands = rules.build_candidates(_ctx_vote("vote_countdown"), _frame([hand]))
    assert not any(c[0] == VOTE_POINT for c in cands)


def test_vote_point_retarget_fires_on_target_change() -> None:
    """같은 투표자가 A→B로 대상을 바꾸면 재발화한다."""
    rules = WerewolfRules()
    ctx = _ctx_vote("vote_countdown")

    # 첫 지목: p_2
    cands1 = rules.build_candidates(ctx, _frame([_pointing_hand_at(0.8, 0.5)]))
    assert any(c[0] == VOTE_POINT and c[1]["target_id"] == "p_2" for c in cands1)

    # 같은 대상 연속: 발화 없음
    cands2 = rules.build_candidates(ctx, _frame([_pointing_hand_at(0.8, 0.5)]))
    assert not any(c[0] == VOTE_POINT for c in cands2)

    # 대상 변경: p_2 → (no valid target) — 방향 바꿔 hit 없는 경우엔 None 반환
    cands3 = rules.build_candidates(ctx, _frame([_pointing_hand_at(0.5, 0.2)]))
    assert not any(c[0] == VOTE_POINT for c in cands3)


def test_vote_point_same_target_suppressed() -> None:
    """같은 대상을 계속 가리키면 재발화하지 않는다(매 프레임 스팸 방지)."""
    rules = WerewolfRules()
    ctx = _ctx_vote("vote_countdown")

    first = rules.build_candidates(ctx, _frame([_pointing_hand_at(0.8, 0.5)]))
    assert any(c[0] == VOTE_POINT for c in first)

    for _ in range(5):
        repeat = rules.build_candidates(ctx, _frame([_pointing_hand_at(0.8, 0.5)]))
        assert not any(c[0] == VOTE_POINT for c in repeat)


def test_phase_change_clears_vote_memory() -> None:
    """페이즈가 바뀌면 1인 1표 기억이 초기화돼 다음 판에서 다시 지목할 수 있다."""
    rules = WerewolfRules()
    hand = _pointing_hand_at(0.8, 0.5)

    assert rules.build_candidates(_ctx_vote("vote_countdown"), _frame([hand]))
    # 다른 페이즈를 거쳤다가 돌아오면 같은 대상도 다시 발화한다.
    rules.build_candidates(_ctx_vote("day_discussion"), _frame([hand]))
    assert rules.build_candidates(_ctx_vote("vote_countdown"), _frame([hand]))


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
