"""RollAttributor 시나리오 테스트 — 손 점유(occlusion) 기반.

핵심 흐름:
  WAITING → 손이 tray 진입 → HAND_IN_TRAY → 손 빠짐 + dice 5개 stable + 변화 → ROLL_CONFIRMED
"""

from __future__ import annotations

from vision.attribution.roll_attributor import RollAttributor, RollState
from vision.schemas import BBox, HandDet
from vision.yacht.schemas import DiceState, YachtFramePerception


def _tray() -> BBox:
    return BBox(0.2, 0.2, 0.8, 0.8, 0.9, "tray")


def _tray_inner() -> BBox:
    return BBox(0.6, 0.2, 0.8, 0.8, 0.9, "tray_inner")


def _hand(player_id: str | None, wrist_xy: tuple[float, float]) -> HandDet:
    return HandDet(
        handedness="Right",
        wrist_xy=wrist_xy,
        landmarks_21=[wrist_xy] * 21,
        gesture=None,
        player_id=player_id,
    )


def _dice(track_id: int, center: tuple[float, float], pip: int | None) -> DiceState:
    cx, cy = center
    return DiceState(
        track_id=track_id,
        bbox=BBox(cx - 0.03, cy - 0.03, cx + 0.03, cy + 0.03, 0.9, "dice"),
        center=center,
        motion_score=0.0001,
        stable_frames=35,
        pip_count=pip,
    )


def _initial_dice() -> list[DiceState]:
    """굴림 전: tray 안 5개 안정."""
    return [_dice(i, (0.3 + 0.05 * i, 0.4), pip=2) for i in range(5)]


def _rolled_dice() -> list[DiceState]:
    """굴림 후: 위치/pip 모두 변경."""
    return [_dice(i, (0.32 + 0.06 * i, 0.5), pip=((i + 3) % 6) + 1) for i in range(5)]


def _frame(
    frame_id: int,
    hands: list[HandDet],
    dice: list[DiceState],
    tray_inner: BBox | None = None,
    roll_tray_in: bool = True,
) -> YachtFramePerception:
    """기본적으로 roll_tray가 tray 안에 있다고 가정.

    roll_tray 진입 게이트 테스트를 위해 roll_tray_in=False로 설정 가능.
    """
    rt = (
        BBox(0.4, 0.4, 0.55, 0.55, 0.9, "roll_tray")
        if roll_tray_in
        else BBox(0.0, 0.0, 0.05, 0.05, 0.9, "roll_tray")
    )
    return YachtFramePerception(
        frame_id=frame_id,
        ts=float(frame_id) / 30.0,
        image_hw=(1080, 1920),
        tray=_tray(),
        tray_inner=tray_inner,
        roll_tray=rt,
        dice=dice,
        hands=hands,
    )


# ── 테스트 ────────────────────────────────────────────────────────────────────


def test_normal_roll_player_a() -> None:
    """A 손이 tray 진입 → 빠진 후 dice 변화 + 안정 → ROLL_CONFIRMED."""
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    # WAITING — 초기 상태
    attr.update(_frame(0, [], _initial_dice()))
    assert attr.state == RollState.WAITING

    # A 손이 tray 진입 → HAND_IN_TRAY
    hand_in = _hand("p_a", (0.5, 0.5))
    attr.update(_frame(1, [hand_in], _initial_dice()))
    assert attr.state == RollState.HAND_IN_TRAY

    # 점유 유지
    attr.update(_frame(2, [hand_in], _initial_dice()))

    # 손이 빠지고 dice가 변화 + 안정 → 발화
    result = attr.update(_frame(3, [], _rolled_dice()))
    assert result == "p_a"
    assert attr.state == RollState.WAITING


def test_brief_touch_does_not_fire() -> None:
    """손은 들어왔다 나갔지만 dice 변화 없음 → 발화 안 함."""
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )
    initial = _initial_dice()

    attr.update(_frame(0, [], initial))
    attr.update(_frame(1, [_hand("p_a", (0.5, 0.5))], initial))
    assert attr.state == RollState.HAND_IN_TRAY

    # 손 빠짐 + dice 그대로 → 변화 점수 0 → 발화 없음
    result = attr.update(_frame(2, [], initial))
    assert result is None
    assert attr.state == RollState.WAITING


def test_two_consecutive_rolls() -> None:
    """연속 2회 굴림 — 각각 ROLL_CONFIRMED 발화."""
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    # 1차 굴림
    attr.update(_frame(0, [], _initial_dice()))
    attr.update(_frame(1, [_hand("p_a", (0.5, 0.5))], _initial_dice()))
    r1 = attr.update(_frame(2, [], _rolled_dice()))
    assert r1 == "p_a"

    # 2차 굴림 — 또 다른 위치/pip
    rolled2 = [_dice(i, (0.5 + 0.04 * i, 0.6), pip=((i * 2) % 6) + 1) for i in range(5)]
    attr.update(_frame(3, [_hand("p_a", (0.5, 0.5))], _rolled_dice()))
    r2 = attr.update(_frame(4, [], rolled2))
    assert r2 == "p_a"


def test_partial_change_above_threshold_fires() -> None:
    """5개 중 일부만 변해도 변화 점수가 임계(0.2) 이상이면 ROLL_CONFIRMED.

    1~2개 빠져나갔다 다시 굴리는 케이스 — 나머지는 그대로여도 발화돼야 함.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    initial = [
        _dice(0, (0.3, 0.4), pip=1),
        _dice(1, (0.4, 0.4), pip=2),
        _dice(2, (0.5, 0.4), pip=3),
        _dice(3, (0.55, 0.4), pip=4),
        _dice(4, (0.6, 0.4), pip=5),
    ]

    attr.update(_frame(0, [], initial))
    attr.update(_frame(1, [_hand("p_a", (0.4, 0.5))], initial))
    assert attr.state == RollState.HAND_IN_TRAY

    # 5개 중 2개만 변화 (재굴림된 dice) — 변화 점수 0.4 ≥ 임계 0.2 → 발화
    rolled = [
        _dice(0, (0.3, 0.4), pip=1),  # 그대로
        _dice(1, (0.4, 0.4), pip=2),  # 그대로
        _dice(2, (0.5, 0.4), pip=3),  # 그대로
        _dice(3, (0.32, 0.55), pip=6),  # 변화 (재굴림)
        _dice(4, (0.42, 0.55), pip=1),  # 변화 (재굴림)
    ]
    result = attr.update(_frame(2, [], rolled))
    assert result == "p_a"


def test_four_kept_one_rerolled_same_pip_fires() -> None:
    """4개 킵 + 1개 재굴림에서 **같은 눈이 다시 나와도** 발화한다.

    눈 분포만 보면 이 굴림은 "아무 일도 없었음"과 구분되지 않는다. 구분되는
    것은 자리다 — 재굴림된 주사위만 원래 있던 자리를 비우고 다른 곳에 앉는다.

    굴림통에 넣었다 쏟은 주사위는 화면에서 사라졌다 나타나므로 ByteTrack이
    새 track_id를 준다. track_id로 짝을 지으면 이 주사위가 비교에서 통째로
    빠지고, 남는 4개는 전부 제자리라 점수가 0이 되어 굴림이 사라졌다.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    initial = [
        _dice(0, (0.30, 0.40), pip=1),
        _dice(1, (0.40, 0.40), pip=2),
        _dice(2, (0.50, 0.40), pip=3),
        _dice(3, (0.55, 0.40), pip=4),
        _dice(4, (0.60, 0.40), pip=5),  # 이 주사위를 다시 굴린다
    ]

    attr.update(_frame(0, [], initial))
    attr.update(_frame(1, [_hand("p_a", (0.4, 0.5))], initial))
    assert attr.state == RollState.HAND_IN_TRAY

    rolled = [
        _dice(0, (0.30, 0.40), pip=1),  # 킵 — 제자리
        _dice(1, (0.40, 0.40), pip=2),  # 킵 — 제자리
        _dice(2, (0.50, 0.40), pip=3),  # 킵 — 제자리
        _dice(3, (0.55, 0.40), pip=4),  # 킵 — 제자리
        # 재굴림: 눈은 5 그대로지만 자리가 바뀌고 track_id가 새로 붙었다
        _dice(97, (0.38, 0.62), pip=5),
    ]
    assert attr.update(_frame(2, [], rolled)) == "p_a"


def test_cover_and_uncover_with_new_track_ids_no_fire() -> None:
    """가림으로 track_id가 전부 새로 붙어도, 자리가 그대로면 발화하지 않는다.

    위 테스트의 반대편 경계다. track_id를 버리고 좌표로 짝을 짓기로 한 이상,
    "track_id가 바뀌었다"가 더는 변화의 근거가 아님을 여기서 못박는다.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    initial = [_dice(i, (0.30 + 0.06 * i, 0.40), pip=i + 1) for i in range(5)]
    attr.update(_frame(0, [], initial))
    attr.update(_frame(1, [_hand("p_a", (0.4, 0.5))], initial))
    assert attr.state == RollState.HAND_IN_TRAY

    # 굴림통이 지나가며 가렸다 치웠다 — 눈도 자리도 그대로, track_id만 재할당.
    same_place = [_dice(100 + i, (0.30 + 0.06 * i, 0.40), pip=i + 1) for i in range(5)]
    assert attr.update(_frame(2, [], same_place)) is None


def _shaking_frames(
    attr: RollAttributor,
    dice: list[DiceState],
    count: int,
    start: int,
    shake: bool = True,
) -> int:
    """손 없이 굴림통만 tray 위에서 흔드는 프레임을 먹인다. 다음 frame_id를 돌려준다."""
    import math

    for i in range(count):
        f = start + i
        cx = 0.5 + (0.05 * math.sin(f) if shake else 0.0)
        attr.update(
            YachtFramePerception(
                frame_id=f,
                ts=f / 30.0,
                image_hw=(1080, 1920),
                tray=_tray(),
                roll_tray=BBox(cx - 0.07, 0.43, cx + 0.07, 0.57, 0.9, "roll_tray"),
                dice=dice,
                hands=[],
            )
        )
    return start + count


def test_roll_fires_when_no_hand_is_ever_detected() -> None:
    """손이 한 번도 안 잡혀도 굴림통이 흔들렸으면 굴림으로 인정한다.

    오버헤드 뷰에서 MediaPipe는 손을 자주 놓친다 — 실측 로그에서 주사위는
    또렷이 잡히는데 손은 50번 중 2번만 잡혔고, 손을 요구하는 가드 때문에 그
    판에서는 아무리 굴려도 처리되지 않았다.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    f = _shaking_frames(attr, _initial_dice(), 5, start=0, shake=False)
    f = _shaking_frames(attr, _initial_dice(), 10, start=f)  # 굴림통을 흔든다
    assert attr.state == RollState.HAND_IN_TRAY

    # 쏟았다 — 굴림통을 tray 밖으로 치우고 주사위가 새 눈으로 돌아온다.
    rolled = _rolled_dice()
    fired = False
    for i in range(15):
        attr.update(_frame(f + i, [], rolled, roll_tray_in=False))
        if attr.just_finalized:
            fired = True
            break
    assert fired, "손을 못 봤다고 굴림이 사라지면 안 된다"


def test_loading_dice_into_the_cup_does_not_fire() -> None:
    """굴림통에 주사위를 담는 동안은 발화하지 않는다.

    손 가드를 흔들림으로도 만족시키게 바꾼 뒤에도 이게 지켜져야 한다. 담는
    동안에는 주사위가 굴림통 안에 있어 화면에 5개가 안 잡히고, 개수 게이트가
    막는다 — 손 가드와 겹쳐 있던 방어선이다.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    all_dice = _initial_dice()
    f = _shaking_frames(attr, all_dice, 5, start=0, shake=False)

    # 5개 → 0개로 하나씩 담는다. 굴림통은 내내 흔들린다.
    for remaining in range(5, -1, -1):
        f = _shaking_frames(attr, all_dice[:remaining], 8, start=f)
        assert not attr.just_finalized, f"{remaining}개 남았을 때 발화했다"


def test_cup_resting_in_tray_does_not_fire() -> None:
    """굴림통이 그냥 놓여만 있으면 흔들림 신호가 서지 않는다."""
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    f = _shaking_frames(attr, _initial_dice(), 10, start=0, shake=False)
    for i in range(10):
        attr.update(_frame(f + i, [], _rolled_dice(), roll_tray_in=False))
        assert not attr.just_finalized, "움직이지 않은 굴림통으로 발화했다"


def test_finger_in_tray_triggers_occupation() -> None:
    """wrist는 밖이지만 손가락 끝이 tray 안이어도 점유로 인정."""
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )
    attr.update(_frame(0, [], _initial_dice()))

    # wrist는 tray 밖, 그러나 검지 끝(landmark[8])이 안에
    finger_hand = HandDet(
        handedness="Right",
        wrist_xy=(0.05, 0.5),  # 밖
        landmarks_21=[(0.05, 0.5)] * 8 + [(0.5, 0.5)] + [(0.05, 0.5)] * 12,
        gesture=None,
        player_id="p_a",
    )
    attr.update(_frame(1, [finger_hand], _initial_dice()))
    assert attr.state == RollState.HAND_IN_TRAY


def test_roll_fires_when_hand_player_id_unconfirmed() -> None:
    """active_player가 정해졌지만 손의 player_id가 아직 미확정(None)인 굴림도 발화.

    실전 회귀: 굴림처럼 짧은 동작에선 player_id 다수결이 굳기 전이라 손에
    player_id가 안 붙는데, finalize 가드가 active_player 필터로 손을 검사하면
    가드가 영원히 안 풀려 발화가 통째로 막혔다. 가드를 무필터로 완화해 해소.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )

    # active_player는 "p_a"로 정해졌지만 감지된 손은 아직 player_id 미확정(None).
    hand_in = _hand(None, (0.5, 0.5))
    attr.update(_frame(0, [], _initial_dice()), active_player="p_a")
    attr.update(_frame(1, [hand_in], _initial_dice()), active_player="p_a")
    assert attr.state == RollState.HAND_IN_TRAY

    attr.update(_frame(2, [hand_in], _initial_dice()), active_player="p_a")
    result = attr.update(_frame(3, [], _rolled_dice()), active_player="p_a")
    # 발화돼야 한다 (가드 통과). actor는 player_id 미확정이라 None일 수 있음.
    assert attr.just_finalized is True
    assert attr.state == RollState.WAITING
    _ = result


def test_no_tray_no_occupation() -> None:
    """tray 미감지면 점유 판정 안 함."""
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )
    perception = YachtFramePerception(
        frame_id=0,
        ts=0.0,
        image_hw=(1080, 1920),
        tray=None,
        dice=_initial_dice(),
        hands=[_hand("p_a", (0.5, 0.5))],
    )
    result = attr.update(perception)
    assert result is None
    assert attr.state == RollState.WAITING


def test_cover_and_uncover_same_pips_no_fire() -> None:
    """roll_tray로 잠깐 가렸다 치우기 — 눈 분포 동일하면 발화 안 함.

    실전 회귀: 가림 시 ByteTrack이 track_id를 재할당하거나 개수가 잠깐
    어긋나 변화 점수가 1.0으로 튀어, 굴리지도 않았는데 ROLL_CONFIRMED가
    발화돼 굴림 횟수가 깎였다. pip 분포(multiset) 비교로 눈이 그대로면 0점.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )
    initial = [_dice(i, (0.3 + 0.05 * i, 0.4), pip=p) for i, p in enumerate([1, 2, 3, 4, 5])]

    attr.update(_frame(0, [], initial))
    attr.update(_frame(1, [_hand("p_a", (0.5, 0.5))], initial))
    assert attr.state == RollState.HAND_IN_TRAY

    # 가렸다 치움: track_id는 새로 부여됐지만 눈 분포는 그대로(위치도 그대로).
    uncovered = [
        _dice(i + 100, (0.3 + 0.05 * i, 0.4), pip=p) for i, p in enumerate([1, 2, 3, 4, 5])
    ]
    result = attr.update(_frame(2, [], uncovered))
    assert result is None
    assert attr.just_finalized is False
    assert attr.state == RollState.WAITING


def test_non_current_player_roll_returns_that_player_as_actor() -> None:
    """차례가 아닌 사람(p_b)이 굴려도 actor는 p_b로 잡힌다 (FSM 차례 경고용).

    실전 회귀: actor 산정이 active_player(p_a) 필터를 걸어, p_b 굴림에서
    actor가 None이 됐다. FSM은 actor=None을 현재 플레이어로 간주해 차례
    경고 없이 정상 처리했다. 필터를 풀어 실제 굴린 사람을 actor로 반환.
    """
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )
    # active_player는 p_a지만 굴리는 손은 p_b.
    hand_b = _hand("p_b", (0.5, 0.5))
    attr.update(_frame(0, [], _initial_dice()), active_player="p_a")
    attr.update(_frame(1, [hand_b], _initial_dice()), active_player="p_a")
    assert attr.state == RollState.HAND_IN_TRAY

    attr.update(_frame(2, [hand_b], _initial_dice()), active_player="p_a")
    result = attr.update(_frame(3, [], _rolled_dice()), active_player="p_a")
    assert result == "p_b"


def test_static_scene_no_fire() -> None:
    """손도 없고 dice 변화도 없으면 영원히 WAITING — 발화 없음."""
    attr = RollAttributor(
        stabilization_frames=3,
        enter_debounce_frames=1,
        exit_debounce_frames=1,
        roll_tray_in_tray_required=1,
    )
    for i in range(20):
        result = attr.update(_frame(i, [], _initial_dice()))
        assert result is None
    assert attr.state == RollState.WAITING
