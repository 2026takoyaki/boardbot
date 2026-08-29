"""한밤의 늑대인간 FSM 테스트.

시스템은 플레이어의 역할을 모른다. 야간 페이즈 진행 여부는 이번 판의 역할
덱(deck_roles)으로만 결정되고, 각 페이즈는 OK 사인(GESTURE_CONFIRMED)으로
넘어간다(타이머는 폴백). 승패는 판정하지 않고 최다 득표자까지만 확정한다.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from agents.tempo_agent import PHASE_END_WARNING_LEAD
from agents.tools import lines, tempo_pool, werewolf_coach
from core.constants import CommonEventType
from core.events import GameEvent
from games.werewolf.fsm import (
    ACTIVE_PHASE_TIMEOUT,
    PASSIVE_PHASE_DURATION,
    VOTE_COUNTDOWN_SECONDS,
    WerewolfFSM,
)
from games.werewolf.ontology import (
    PHASE_TO_ROLE,
    WerewolfEventType,
    WerewolfInputType,
    WerewolfPhase,
)
from games.werewolf.state import WerewolfPlayerState

# 야간 페이즈가 있는 모든 역할 + 마을주민. 특정 역할의 유무를 검증하지 않는 테스트에서 쓴다.
FULL_DECK = [r.value for r in PHASE_TO_ROLE.values()] + ["villager"]


def _make_fsm(
    deck_roles: list[str] | None = None,
    broadcast=None,
    player_count: int = 3,
    practice_mode: bool = False,
) -> WerewolfFSM:
    if broadcast is None:

        async def _noop(_msg):
            pass

        broadcast = _noop
    players = [WerewolfPlayerState(player_id=f"p_{i}") for i in range(player_count)]
    return WerewolfFSM(
        players=players,
        deck_roles=deck_roles if deck_roles is not None else list(FULL_DECK),
        broadcast=broadcast,
        practice_mode=practice_mode,
    )


def _gesture(actor_id: str = "p_0") -> GameEvent:
    return GameEvent(
        event_type=CommonEventType.GESTURE_CONFIRMED,
        actor_id=actor_id,
        confidence=0.9,
        frame_id=1,
        data={"gesture": "ok_sign"},
    )


# ── 야간 발화 예산 ────────────────────────────────────────────────────────────
#
# "눈을 다시 감아주세요"가 못 나오면 눈을 언제 감을지 아무도 모른다. 그 지시가
# 단계 안에 반드시 들어가도록 시간을 문장 길이에서 거꾸로 잡았는데, 문장은
# 나중에 얼마든지 길어질 수 있다. 그때 조용히 잘리는 대신 여기서 실패한다.

_CHARS_PER_SEC = 5.0  # 보수적(느리게 읽는 쪽) 추정. fsm.py의 주석과 같은 값.
_ACT_ACTIVE = 4.0  # 카드를 실제로 다루는 시간
_ACT_PASSIVE = 3.0  # 서로 확인하는 시간


def _longest_across_personas(line_id: str) -> int:
    """기본 문구와 출고된 페르소나 문구 중 가장 긴 것의 글자 수.

    한 페르소나만 길어도 그 사람 판에서만 지시가 잘린다. 최댓값으로 잡아야
    누구를 골라도 안전하다.
    """
    import json
    from pathlib import Path

    longest = len(lines.get(line_id) or "")
    persona_dir = Path(__file__).resolve().parent.parent / "agents" / "tools" / "persona_lines"
    for path in sorted(persona_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        catalog = data.get("lines", data)
        longest = max(longest, len(catalog.get(line_id) or ""))
    return longest


def test_야간_단계에_마감_지시까지_들어갈_시간이_있다() -> None:
    short: list[str] = []

    for phase, tip_id in werewolf_coach.PHASE_TIPS.items():
        chars = _longest_across_personas(f"werewolf.{phase}") + _longest_across_personas(tip_id)
        need = chars / _CHARS_PER_SEC + _ACT_ACTIVE + PHASE_END_WARNING_LEAD
        if need > ACTIVE_PHASE_TIMEOUT:
            short.append(f"{phase} {need:.1f}초 필요 > {ACTIVE_PHASE_TIMEOUT}초")

    for phase in ("night_werewolf", "night_minion", "night_mason"):
        chars = _longest_across_personas(f"werewolf.{phase}")
        need = chars / _CHARS_PER_SEC + _ACT_PASSIVE + PHASE_END_WARNING_LEAD
        if need > PASSIVE_PHASE_DURATION:
            short.append(f"{phase} {need:.1f}초 필요 > {PASSIVE_PHASE_DURATION}초")

    assert not short, (
        "야간 단계가 짧아 '눈을 다시 감아주세요'가 잘린다. "
        f"멘트를 줄이거나 단계 시간을 늘려라: {short}"
    )


def test_마감_지시는_리드_시간_안에_읽힌다() -> None:
    """지시를 읽는 시간 + 눈을 감을 시간이 리드 안에 들어가야 한다."""
    cap = tempo_pool.max_len("tempo.close_eyes_again")
    speaking = cap / _CHARS_PER_SEC
    assert (
        speaking < PHASE_END_WARNING_LEAD
    ), f"마감 지시 상한 {cap}자({speaking:.1f}초)가 리드 {PHASE_END_WARNING_LEAD}초를 채운다"
    # 출고된 문구가 상한을 지키는지도 함께 본다 — 상한만 있고 안 지키면 소용없다.
    actual = _longest_across_personas("tempo.close_eyes_again")
    assert actual <= cap, f"출고된 마감 지시가 {actual}자로 상한 {cap}자를 넘는다"


# ── 페이즈 시간 전달 ──────────────────────────────────────────────────────────


def test_state_update_carries_phase_duration() -> None:
    """화면의 카운트다운이 쓸 시간을 상태에 실어 보낸다.

    예전에는 화면이 이 숫자를 자기 파일에 복사해 갖고 있어서, 백엔드 시간만
    바꾸면 숫자가 0이 되어도 단계가 안 넘어가는 상태가 됐다. 숫자의 주인은
    타이머를 가진 FSM이다.
    """
    fsm = _make_fsm()

    fsm.state.phase = WerewolfPhase.NIGHT_WEREWOLF.value  # 패시브
    assert fsm._make_state_update().payload["phase_duration"] == PASSIVE_PHASE_DURATION

    fsm.state.phase = WerewolfPhase.NIGHT_SEER.value  # 액티브
    assert fsm._make_state_update().payload["phase_duration"] == ACTIVE_PHASE_TIMEOUT

    # 타이머가 없는 페이즈는 None — 화면이 가짜 카운트다운을 돌리지 않게 한다.
    fsm.state.phase = WerewolfPhase.DAY_DISCUSSION.value
    assert fsm._make_state_update().payload["phase_duration"] is None


def test_practice_mode_has_no_fixed_phase_duration() -> None:
    """튜토리얼은 안내 TTS가 끝난 뒤 화면이 전이를 주도한다. 고정 시간이 없다."""
    fsm = _make_fsm(practice_mode=True)
    fsm.state.phase = WerewolfPhase.NIGHT_SEER.value
    assert fsm._make_state_update().payload["phase_duration"] is None


# ── 패시브 타이머 ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_passive_werewolf_phase_auto_advances() -> None:
    """night_werewolf 진입 후 타이머 경과 시 자동 전환."""
    fsm = _make_fsm()

    with patch("games.werewolf.fsm.PASSIVE_PHASE_DURATION", 0):
        fsm._enter_phase(WerewolfPhase.NIGHT_WEREWOLF)
        await asyncio.sleep(0.05)

    assert fsm.state.phase != WerewolfPhase.NIGHT_WEREWOLF.value


@pytest.mark.anyio
async def test_passive_timer_skips_if_phase_already_changed() -> None:
    """phase가 이미 변경된 경우 패시브 타이머 콜백이 전환 skip."""
    broadcast_msgs: list = []

    async def record(msg):
        broadcast_msgs.append(msg)

    fsm = _make_fsm(broadcast=record)
    fsm.state.phase = WerewolfPhase.DAY_DISCUSSION.value

    initial_version = fsm.state.state_version
    with patch("games.werewolf.fsm.PASSIVE_PHASE_DURATION", 0):
        await fsm._run_passive_timer(WerewolfPhase.NIGHT_WEREWOLF)

    assert fsm.state.phase == WerewolfPhase.DAY_DISCUSSION.value
    assert fsm.state.state_version == initial_version


# ── 액티브 타이머 ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_active_timeout_advances_phase_when_no_event() -> None:
    """OK 사인이 유실돼도 타임아웃 폴백으로 강제 전환된다."""
    fsm = _make_fsm()

    with patch("games.werewolf.fsm.ACTIVE_PHASE_TIMEOUT", 0):
        fsm._enter_phase(WerewolfPhase.NIGHT_SEER)
        await asyncio.sleep(0.05)

    assert fsm.state.phase != WerewolfPhase.NIGHT_SEER.value


@pytest.mark.anyio
async def test_active_timer_skips_if_phase_already_changed() -> None:
    """phase가 이미 변경된 경우 액티브 타이머 콜백이 전환 skip."""
    fsm = _make_fsm()
    fsm.state.phase = WerewolfPhase.DAY_DISCUSSION.value

    initial_version = fsm.state.state_version
    with patch("games.werewolf.fsm.ACTIVE_PHASE_TIMEOUT", 0):
        await fsm._run_active_timer(WerewolfPhase.NIGHT_SEER)

    assert fsm.state.phase == WerewolfPhase.DAY_DISCUSSION.value
    assert fsm.state.state_version == initial_version


@pytest.mark.anyio
async def test_active_timer_cancelled_on_new_phase_entry() -> None:
    """새 phase 진입 시 이전 액티브 타이머가 취소되고 _active_timer_task가 None으로 초기화됨."""
    fsm = _make_fsm()

    with patch("games.werewolf.fsm.ACTIVE_PHASE_TIMEOUT", 60):
        fsm._enter_phase(WerewolfPhase.NIGHT_SEER)
        await asyncio.sleep(0)
        task = fsm._active_timer_task
        assert task is not None and not task.done()

        fsm._enter_phase(WerewolfPhase.DAY_DISCUSSION)
        await asyncio.sleep(0)

    # _run_active_timer가 CancelledError를 내부에서 catch하므로 task.cancelled()는 False.
    # cancel()이 전송되었음을 확인: task가 done 상태이고 fsm의 참조가 None으로 초기화됨.
    assert task.done()
    assert fsm._active_timer_task is None


# ── OK 사인으로 야간 진행 ──────────────────────────────────────────────────────


def _cancel_timers(fsm: WerewolfFSM) -> None:
    for attr in ("_timer_task", "_passive_timer_task", "_active_timer_task"):
        task = getattr(fsm, attr)
        if task and not task.done():
            task.cancel()


@pytest.mark.anyio
async def test_gesture_advances_active_night_phase() -> None:
    """액티브 역할 페이즈도 OK 사인으로 넘어간다(카드 감지 대체 경로)."""
    fsm = _make_fsm()
    fsm.state.phase = WerewolfPhase.NIGHT_SEER.value

    msgs = fsm.handle_event(_gesture())

    assert fsm.state.phase != WerewolfPhase.NIGHT_SEER.value
    assert msgs
    _cancel_timers(fsm)


@pytest.mark.anyio
async def test_gesture_advances_passive_night_phase() -> None:
    """패시브 역할 페이즈에서도 기존대로 OK 사인이 동작한다."""
    fsm = _make_fsm()
    fsm.state.phase = WerewolfPhase.NIGHT_WEREWOLF.value

    fsm.handle_event(_gesture())

    assert fsm.state.phase != WerewolfPhase.NIGHT_WEREWOLF.value
    _cancel_timers(fsm)


@pytest.mark.anyio
async def test_gesture_ignored_during_night_start() -> None:
    """night_start 안내 화면은 OK 사인으로 넘어가지 않는다.

    직전 card_setup_confirm에서 든 OK 손이 그대로 남아 있으면 페이즈 전환 직후
    같은 손이 재발화해 안내 화면이 1~2초 만에 사라졌다.
    """
    fsm = _make_fsm()
    assert fsm.state.phase == WerewolfPhase.NIGHT_START.value

    assert fsm.handle_event(_gesture()) == []

    assert fsm.state.phase == WerewolfPhase.NIGHT_START.value
    _cancel_timers(fsm)


@pytest.mark.anyio
async def test_night_start_auto_advances_after_duration() -> None:
    """일반 모드는 NIGHT_START_DURATION 초 뒤 첫 밤 역할 페이즈로 자동 전이한다."""
    fsm = _make_fsm()

    with patch("games.werewolf.fsm.NIGHT_START_DURATION", 0):
        fsm.start()
        await asyncio.sleep(0.05)

    assert fsm.state.phase != WerewolfPhase.NIGHT_START.value
    _cancel_timers(fsm)


@pytest.mark.anyio
async def test_night_start_has_no_backend_timer_in_practice_mode() -> None:
    """튜토리얼 모드는 안내 TTS 종료 후 프론트가 start_now로 전이를 주도한다."""
    fsm = _make_fsm(practice_mode=True)

    with patch("games.werewolf.fsm.NIGHT_START_DURATION", 0):
        fsm.start()
        await asyncio.sleep(0.05)

    assert fsm.state.phase == WerewolfPhase.NIGHT_START.value
    assert fsm._passive_timer_task is None

    fsm.handle_input(WerewolfInputType.START_NOW, {})
    assert fsm.state.phase != WerewolfPhase.NIGHT_START.value
    _cancel_timers(fsm)


def test_gesture_ignored_outside_night() -> None:
    """토론·투표 중 OK 사인은 페이즈를 넘기지 않는다."""
    for phase in (WerewolfPhase.DAY_DISCUSSION, WerewolfPhase.VOTE_COUNTDOWN):
        fsm = _make_fsm()
        fsm.state.phase = phase.value
        assert fsm.handle_event(_gesture()) == []
        assert fsm.state.phase == phase.value


@pytest.mark.anyio
async def test_gesture_cancels_active_timer() -> None:
    """OK 사인으로 전이하면 남아 있던 액티브 폴백 타이머가 취소된다."""
    fsm = _make_fsm()

    with patch("games.werewolf.fsm.ACTIVE_PHASE_TIMEOUT", 60):
        fsm._enter_phase(WerewolfPhase.NIGHT_SEER)
        await asyncio.sleep(0)
        task = fsm._active_timer_task
        assert task is not None and not task.done()

        fsm.handle_event(_gesture())
        await asyncio.sleep(0)

    assert task.done()


def test_card_events_no_longer_handled() -> None:
    """제거된 카드 이벤트가 흘러들어와도 FSM은 무시한다."""
    fsm = _make_fsm()
    fsm.state.phase = WerewolfPhase.NIGHT_SEER.value

    stale = GameEvent(
        event_type="werewolf_card_peek",
        actor_id="p_0",
        confidence=0.9,
        frame_id=1,
        data={"card_owner_id": "p_1", "card_index": 0},
    )
    assert fsm.handle_event(stale) == []
    assert fsm.state.phase == WerewolfPhase.NIGHT_SEER.value


# ── 투표 카운트다운 & lock ────────────────────────────────────────────────────


def _set_vote_countdown_state(fsm: WerewolfFSM) -> None:
    """테스트용: VOTE_COUNTDOWN 상태를 직접 설정한다 (타이머 task 없이)."""
    fsm.state.phase = WerewolfPhase.VOTE_COUNTDOWN.value
    fsm.state.votes_locked = False
    fsm.state.countdown_remaining = VOTE_COUNTDOWN_SECONDS
    for p in fsm.state.players:
        p.voted_for = None
    fsm.state.state_version += 1


@pytest.mark.anyio
async def test_vote_countdown_enter_initializes_flags() -> None:
    """VOTE_COUNTDOWN 진입(_enter_phase) 시 votes_locked=False, 카운트다운은 아직 미시작(None)."""
    fsm = _make_fsm()
    fsm.state.phase = WerewolfPhase.DAY_DISCUSSION.value
    fsm._advance_to_next_phase()
    await asyncio.sleep(0)  # task 스케줄 양보

    assert fsm.state.phase == WerewolfPhase.VOTE_COUNTDOWN.value
    assert fsm.state.votes_locked is False
    # 안내 TTS 종료 후 VOTE_COUNTDOWN_START 입력으로 시작하므로 진입 직후엔 None.
    assert fsm.state.countdown_remaining is None


@pytest.mark.anyio
async def test_vote_countdown_start_input_begins_countdown() -> None:
    """VOTE_COUNTDOWN_START 입력 시 카운트다운이 시작되고, 중복 입력은 무시된다."""
    fsm = _make_fsm()
    fsm.state.phase = WerewolfPhase.DAY_DISCUSSION.value
    fsm._advance_to_next_phase()
    await asyncio.sleep(0)
    assert fsm.state.countdown_remaining is None

    fsm.handle_input(WerewolfInputType.VOTE_COUNTDOWN_START, {}, None)
    assert fsm.state.countdown_remaining == VOTE_COUNTDOWN_SECONDS

    # 중복 신호(워치독+TTS 종료 동시 등)는 카운트다운 값을 리셋하지 않는다.
    fsm.state.countdown_remaining = 2
    fsm.handle_input(WerewolfInputType.VOTE_COUNTDOWN_START, {}, None)
    assert fsm.state.countdown_remaining == 2

    if fsm._active_timer_task:
        fsm._active_timer_task.cancel()


@pytest.mark.anyio
async def test_vote_countdown_enter_clears_votes() -> None:
    """VOTE_COUNTDOWN 진입 시 모든 플레이어의 voted_for가 None으로 초기화된다."""
    fsm = _make_fsm()
    for p in fsm.state.players:
        p.voted_for = "p_0"
    fsm.state.phase = WerewolfPhase.DAY_DISCUSSION.value
    fsm._advance_to_next_phase()
    await asyncio.sleep(0)

    assert all(p.voted_for is None for p in fsm.state.players)


def test_vision_vote_updates_voted_for_before_lock() -> None:
    """lock 전 비전 지목은 voted_for를 갱신하고 자동 전이하지 않는다."""
    fsm = _make_fsm()
    _set_vote_countdown_state(fsm)

    event = GameEvent(
        event_type=WerewolfEventType.VOTE_POINT,
        actor_id="p_0",
        confidence=0.9,
        frame_id=1,
        data={"target_id": "p_1"},
    )
    msgs = fsm.handle_event(event)

    assert fsm.state.get_player("p_0").voted_for == "p_1"
    assert fsm.state.phase == WerewolfPhase.VOTE_COUNTDOWN.value
    assert any(True for _ in msgs)  # state_update 발송 확인


def test_vision_vote_allows_retarget() -> None:
    """lock 전 같은 투표자가 A→B로 재지목하면 voted_for가 갱신된다."""
    fsm = _make_fsm()
    _set_vote_countdown_state(fsm)

    def _vote(actor, target):
        return fsm.handle_event(
            GameEvent(
                event_type=WerewolfEventType.VOTE_POINT,
                actor_id=actor,
                confidence=0.9,
                frame_id=1,
                data={"target_id": target},
            )
        )

    _vote("p_0", "p_1")
    assert fsm.state.get_player("p_0").voted_for == "p_1"

    _vote("p_0", "p_2")
    assert fsm.state.get_player("p_0").voted_for == "p_2"


def test_vision_vote_rejected_after_lock() -> None:
    """lock 후 비전 지목은 무시된다."""
    fsm = _make_fsm()
    _set_vote_countdown_state(fsm)
    fsm.state.votes_locked = True

    event = GameEvent(
        event_type=WerewolfEventType.VOTE_POINT,
        actor_id="p_0",
        confidence=0.9,
        frame_id=1,
        data={"target_id": "p_1"},
    )
    msgs = fsm.handle_event(event)

    assert fsm.state.get_player("p_0").voted_for is None
    assert msgs == []


def test_manual_vote_allowed_after_lock() -> None:
    """lock 후에도 werewolf_vote_player(수동 보정)는 voted_for를 갱신한다."""
    fsm = _make_fsm()
    _set_vote_countdown_state(fsm)
    fsm.state.votes_locked = True

    msgs = fsm.handle_input(WerewolfInputType.VOTE_PLAYER, {"target_id": "p_1"}, "p_0")

    assert fsm.state.get_player("p_0").voted_for == "p_1"
    assert msgs  # state_update 발송 확인


def test_vote_result_confirm_only_when_locked() -> None:
    """VOTE_RESULT_CONFIRM은 votes_locked=True 상태에서만 페이즈 전이를 일으킨다."""
    fsm = _make_fsm()
    _set_vote_countdown_state(fsm)

    # lock 전 → 무시
    msgs = fsm.handle_input(WerewolfInputType.VOTE_RESULT_CONFIRM, {}, None)
    assert msgs == []
    assert fsm.state.phase == WerewolfPhase.VOTE_COUNTDOWN.value

    # lock 후 → 다음 페이즈로 전이
    fsm.state.votes_locked = True
    msgs = fsm.handle_input(WerewolfInputType.VOTE_RESULT_CONFIRM, {}, None)
    assert msgs
    assert fsm.state.phase != WerewolfPhase.VOTE_COUNTDOWN.value


# ── 종료: 승패 판정 없이 최다 득표자만 확정 ────────────────────────────────────


def test_result_records_executed_without_winner() -> None:
    """투표 종료 시 RESULT로 직행하고 최다 득표자를 확정한다. 승리팀은 계산하지 않는다."""
    fsm = _make_fsm()
    _set_vote_countdown_state(fsm)
    fsm.state.get_player("p_0").voted_for = "p_1"
    fsm.state.get_player("p_1").voted_for = "p_2"
    fsm.state.get_player("p_2").voted_for = "p_1"
    fsm.state.votes_locked = True

    fsm.handle_input(WerewolfInputType.VOTE_RESULT_CONFIRM, {}, None)

    assert fsm.state.phase == WerewolfPhase.RESULT.value
    assert fsm.state.executed == ["p_1"]
    assert "winner" not in fsm.get_state_dict()


def test_result_no_execution_when_votes_fully_split() -> None:
    """3인 이상에서 전원 1표씩 분산되면 처형자가 없다."""
    fsm = _make_fsm()
    _set_vote_countdown_state(fsm)
    fsm.state.get_player("p_0").voted_for = "p_1"
    fsm.state.get_player("p_1").voted_for = "p_2"
    fsm.state.get_player("p_2").voted_for = "p_0"
    fsm.state.votes_locked = True

    fsm.handle_input(WerewolfInputType.VOTE_RESULT_CONFIRM, {}, None)

    assert fsm.state.phase == WerewolfPhase.RESULT.value
    assert fsm.state.executed == []


# ── 야간 페이즈 필터링 (덱 기준) ──────────────────────────────────────────────


def test_night_phase_included_when_role_in_deck() -> None:
    """덱에 카드가 있으면 해당 야간 페이즈를 진행한다."""
    fsm = _make_fsm(["werewolf", "seer", "villager"])
    assert fsm._night_phase_included(WerewolfPhase.NIGHT_SEER) is True


def test_night_phase_skipped_when_role_absent_from_deck() -> None:
    """덱에 없는 역할의 야간 페이즈는 건너뛴다."""
    fsm = _make_fsm(["werewolf", "villager", "robber"])
    assert fsm._night_phase_included(WerewolfPhase.NIGHT_SEER) is False


def test_night_phase_included_even_if_card_may_sit_in_center() -> None:
    """덱에 있으면 그 카드가 센터에 깔렸을 수 있어도 호명한다.

    시스템은 배분 결과를 모른다. 호명을 건너뛰면 그 역할이 아무에게도 없다는
    사실이 드러나므로, 덱 기준으로 항상 진행하는 것이 정보 은닉 측면에서도 맞다.
    """
    fsm = _make_fsm(["werewolf", "seer", "villager", "villager", "villager", "villager"])
    assert fsm._night_phase_included(WerewolfPhase.NIGHT_SEER) is True


def test_tutorial_mode_skips_roles_not_selected_for_this_game() -> None:
    """튜토리얼 모드도 일반 모드와 동일하게 이번 판 덱 구성만 따른다."""
    fsm = _make_fsm(["seer", "villager", "robber"], practice_mode=True)
    assert fsm._night_phase_included(WerewolfPhase.NIGHT_WEREWOLF) is False
    assert fsm._night_phase_included(WerewolfPhase.NIGHT_MINION) is False
    assert fsm._night_phase_included(WerewolfPhase.NIGHT_MASON) is False
    assert fsm._night_phase_included(WerewolfPhase.NIGHT_SEER) is True


@pytest.mark.anyio
async def test_advance_skips_roles_absent_from_deck() -> None:
    """전체 전이: 덱에 없는 seer를 건너뛰고 robber로 진행한다."""
    fsm = _make_fsm(["werewolf", "robber", "villager"])
    fsm.state.phase = WerewolfPhase.NIGHT_MASON.value
    with patch("games.werewolf.fsm.ACTIVE_PHASE_TIMEOUT", 60):
        fsm._advance_to_next_phase()
    assert fsm.state.phase == WerewolfPhase.NIGHT_ROBBER.value
    if fsm._active_timer_task:
        fsm._active_timer_task.cancel()


@pytest.mark.anyio
async def test_advance_reaches_day_when_no_night_roles_left() -> None:
    """남은 야간 역할이 없으면 토론 단계로 넘어간다."""
    fsm = _make_fsm(["villager", "tanner", "hunter"])
    fsm.state.phase = WerewolfPhase.NIGHT_START.value
    fsm._advance_to_next_phase()
    await asyncio.sleep(0)

    assert fsm.state.phase == WerewolfPhase.DAY_DISCUSSION.value
    if fsm._timer_task:
        fsm._timer_task.cancel()


@pytest.mark.anyio
async def test_countdown_timer_decrements_and_locks() -> None:
    """_run_vote_countdown 실행 시 countdown_remaining이 감소하고 최종적으로 lock된다."""
    fsm = _make_fsm()

    with (
        patch("games.werewolf.fsm.VOTE_COUNTDOWN_SECONDS", 2),
        patch("games.werewolf.fsm.VOTE_LOCK_GRACE", 0),
    ):
        fsm.state.phase = WerewolfPhase.DAY_DISCUSSION.value
        fsm._advance_to_next_phase()
        # 안내 TTS 종료 신호로 카운트다운을 시작한다.
        fsm.handle_input(WerewolfInputType.VOTE_COUNTDOWN_START, {}, None)
        # 카운트다운 완료 + grace 대기
        await asyncio.sleep(2.2)

    assert fsm.state.votes_locked is True
    assert fsm.state.countdown_remaining is None
