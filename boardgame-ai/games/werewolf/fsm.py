"""한밤의 늑대인간 게임 FSM.

시스템은 플레이어의 역할을 알지 못한다. 이번 판의 역할 덱(deck_roles)만 알고
있으므로 야간 페이즈는 덱에 포함된 모든 역할을 순서대로 호명하고, 각 페이즈는
플레이어의 OK 사인(GESTURE_CONFIRMED)으로 넘어간다. 제스처가 유실될 경우를 대비해
고정 타이머를 폴백으로 둔다. 승패는 판정하지 않고 투표 집계까지만 발표한다.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from core.constants import CommonEventType, MsgType
from core.envelope import WSMessage
from core.events import FusionContext, GameEvent
from games.base_fsm import BaseFSM
from games.werewolf.judge import find_executed
from games.werewolf.ontology import (
    NIGHT_PHASES,
    PASSIVE_NIGHT_PHASES,
    PHASE_TO_ROLE,
    WerewolfEventType,
    WerewolfInputType,
    WerewolfPhase,
)
from games.werewolf.state import WerewolfGameState, WerewolfPlayerState

VOTE_COUNTDOWN_SECONDS = 5   # "5,4,3,2,1" 카운트다운 시작값
# 카운트다운 0 도달 후 지목 유예 시간(초).
#
# 비전이 지목을 표로 인정하려면 같은 사람을 몇 프레임 붙잡고 있어야 한다
# (vision/fusion/werewolf_rules.py의 _POINT_HOLD_FRAMES). MediaPipe가 CPU에서
# 10fps 근처로 돌면 그 판정에만 0.4초가 든다. 유예가 그보다 짧으면 마지막에
# 손을 든 사람의 표가 판정 도중에 잘린다 — 실제로 마지막 투표가 자주 빠졌다.
VOTE_LOCK_GRACE = 1.0


# 밤 단계 시간. 각 단계는 조명이 소등을 거쳐 다음 역할 색으로 올라오는 것으로
# 시작한다(bulb/scenes.py의 NIGHT_DIP_*, 약 2.3초). 그 시간은 플레이어가 아직
# 아무것도 할 수 없는 구간이므로, 실제로 행동할 시간은 아래 값에서 그만큼 뺀
# 나머지다. 조명 연출을 넣으면서 그 길이만큼 함께 늘렸다 — 안 늘리면 조명이
# 다 오르기도 전에 다음 단계로 넘어간다.
# ── 야간 단계 길이 ───────────────────────────────────────────────────────────
#
# 한 단계 안에서 이 순서가 전부 끝나야 한다:
#
#     안내 → (조언) → [플레이어가 행동] → "눈을 다시 감아주세요"
#
# **마지막 지시는 빼먹을 수 없다.** 그게 빠지면 눈을 언제 감아야 하는지 아무도
# 모르고, 다음 역할이 호명될 때 이전 역할이 아직 눈을 뜨고 있게 된다.
#
# 그래서 시간을 감으로 잡지 않고 **문장 길이에서 거꾸로** 잡는다:
#
#     필요한 시간 = (안내 + 조언) / 초당글자수 + 행동시간 + 마감 리드
#
# 초당 글자 수는 5.0으로 보수적으로(느리게 읽는 쪽) 잡았고, 문장 길이는
# 페르소나 넷을 포함한 최댓값을 쓴다 — 한 페르소나만 길어도 그 사람 판에서만
# 지시가 잘리기 때문이다. 마감 리드는 agents/tempo_agent.PHASE_END_WARNING_LEAD.
#
# 아래 값은 그 계산의 결과다 (최악: 주정뱅이 81자 → 25.2초, 하수인 38자 → 15.6초).
# 문장을 고치면 이 값도 다시 잡아야 하며, tests/test_werewolf_fsm.py 가 그
# 관계를 검사해 부족하면 실패한다.
#
# 늘리는 대가는 거의 없다 — 둘 다 타임아웃이고, 정상 플레이에서는 OK 사인이
# 먼저 들어와 그 자리에서 끝난다. 제스처를 놓쳤을 때만 이 시간이 다 쓰인다.
PASSIVE_PHASE_DURATION = 16  # 패시브 역할 (조언 없음)
ACTIVE_PHASE_TIMEOUT = 26    # 액티브 역할 (조언 붙음)
NIGHT_START_DURATION = 5     # "밤이 되었습니다" 안내 화면 표시 시간(초)

ACTIVE_NIGHT_PHASES = frozenset({
    WerewolfPhase.NIGHT_DOPPELGANGER,
    WerewolfPhase.NIGHT_SEER,
    WerewolfPhase.NIGHT_ROBBER,
    WerewolfPhase.NIGHT_TROUBLEMAKER,
    WerewolfPhase.NIGHT_DRUNK,
    WerewolfPhase.NIGHT_INSOMNIAC,
})


class WerewolfFSM(BaseFSM):
    def __init__(
        self,
        players: list[WerewolfPlayerState],
        deck_roles: list[str],
        broadcast: Callable[[WSMessage], Awaitable[None]],
        seat_positions: dict[str, tuple[float, float]] | None = None,
        practice_mode: bool = False,
    ) -> None:
        self.state = WerewolfGameState.new(players, deck_roles)
        self._broadcast = broadcast
        self._practice_mode = practice_mode
        self._seat_positions: dict[str, tuple[float, float]] = seat_positions or {}
        self._timer_task: asyncio.Task[None] | None = None
        self._passive_timer_task: asyncio.Task[None] | None = None
        self._active_timer_task: asyncio.Task[None] | None = None

    # ── Public API ──────────────────────────────────────────────────────────────

    def start(self) -> list[WSMessage]:
        """게임을 시작한다. NIGHT_START 안내 화면에서 대기.

        일반 모드는 NIGHT_START_DURATION 초 후 자동으로 첫 야간 역할로 전이한다.
        튜토리얼 모드는 안내 TTS가 길어 프론트가 TTS 종료 후 start_now로 전이를
        주도하므로(다른 페이즈와 동일) 백엔드 타이머를 걸지 않는다.
        """
        self.state.state_version += 1
        if not self._practice_mode:
            self._passive_timer_task = asyncio.create_task(
                self._run_passive_timer(
                    WerewolfPhase.NIGHT_START, NIGHT_START_DURATION
                )
            )
        ctx_msg = WSMessage.make_fusion_context(
            self.get_fusion_context(),
            state_version=self.state.state_version,
        )
        return [self._make_state_update(), ctx_msg]

    def handle_event(self, event: GameEvent) -> list[WSMessage]:
        etype = event.event_type
        if etype == WerewolfEventType.VOTE_POINT:
            return self._handle_vote_point(event)
        if etype == CommonEventType.GESTURE_CONFIRMED:
            return self._handle_gesture_confirmed()
        return []

    def handle_input(
        self,
        input_type: str,
        data: dict,
        player_id: str | None = None,
    ) -> list[WSMessage]:
        if input_type == WerewolfInputType.ADD_30_SEC:
            return self._handle_add_30_sec()
        if input_type == WerewolfInputType.START_NOW:
            return self._handle_start_now()
        if input_type == WerewolfInputType.VOTE_PLAYER:
            return self._handle_vote_player(player_id, data)
        if input_type == WerewolfInputType.VOTE_RESULT_CONFIRM:
            return self._handle_vote_result_confirm()
        if input_type == WerewolfInputType.VOTE_COUNTDOWN_START:
            return self._handle_vote_countdown_start()
        return []

    def get_fusion_context(self) -> FusionContext:
        """비전에 내려보낼 기대 이벤트를 결정한다.

        역할을 모르므로 actor를 특정할 수 없다. 야간 페이즈는 액티브/패시브 구분 없이
        전원에게 OK 사인을 열어두고, 투표만 좌석 좌표 기반 포인팅을 받는다.
        """
        phase = WerewolfPhase(self.state.phase)

        if phase in (WerewolfPhase.VOTE_COUNTDOWN, WerewolfPhase.VOTE):
            seat_anchors = {
                f"seat_{pid}": {"x": x, "y": y}
                for pid, (x, y) in self._seat_positions.items()
            }
            return FusionContext(
                fsm_state=phase.value,
                game_type="werewolf",
                active_player=None,
                allowed_actors=list(self.state.player_order),
                expected_events=[WerewolfEventType.VOTE_POINT],
                reject_events=[CommonEventType.GESTURE_CONFIRMED],
                valid_targets={"player_ids": list(self.state.player_order)},
                zones={},
                anchors=seat_anchors,
                params={"pointing_stabilization_frames": 1},
            )

        # NIGHT_START("밤이 되었습니다")는 확인할 행동이 없는 안내 화면이라 OK 사인을
        # 받지 않는다. 직전 card_setup_confirm 단계에서 든 OK 손이 그대로 남아 있는데,
        # 페이즈가 바뀌면 FusionEngine의 1회 발화 가드(_gesture_confirmed_emitted)가
        # 초기화되므로 같은 손이 곧바로 재발화해 안내 화면이 1~2초 만에 넘어갔다.
        if phase == WerewolfPhase.NIGHT_START:
            return FusionContext(
                fsm_state=phase.value,
                game_type="werewolf",
                active_player=None,
                allowed_actors=[],
                expected_events=[],
                reject_events=[
                    CommonEventType.GESTURE_CONFIRMED,
                    WerewolfEventType.VOTE_POINT,
                ],
                valid_targets=None,
                zones={},
                anchors={},
                params={},
            )

        # 야간 역할 페이즈: 행동을 마친 플레이어가 OK 사인을 보이면 다음으로 넘어간다.
        if phase in NIGHT_PHASES:
            return FusionContext(
                fsm_state=phase.value,
                game_type="werewolf",
                active_player=None,
                allowed_actors=list(self.state.player_order),
                expected_events=[CommonEventType.GESTURE_CONFIRMED],
                reject_events=[WerewolfEventType.VOTE_POINT],
                valid_targets=None,
                zones={},
                anchors={},
                params={},
            )

        # 기본: 이벤트 없음 (DAY_DISCUSSION, RESULT 등)
        return FusionContext(
            fsm_state=phase.value,
            game_type="werewolf",
            active_player=None,
            allowed_actors=[],
            expected_events=[],
            reject_events=[
                CommonEventType.GESTURE_CONFIRMED,
                WerewolfEventType.VOTE_POINT,
            ],
            valid_targets=None,
            zones={},
            anchors={},
            params={},
        )

    def get_state_dict(self) -> dict:
        return self.state.to_dict()

    # ── Internal helpers ────────────────────────────────────────────────────────

    def _night_phase_included(self, phase: WerewolfPhase) -> bool:
        """야간 페이즈 진행 여부 판정.

        누가 어떤 역할을 가졌는지 모르므로 이번 판의 역할 덱에 카드가 들어 있으면
        진행한다. 덱에 있어도 실제로는 센터에 깔려 아무도 행동하지 않을 수 있는데,
        그 경우에도 호명해야 어떤 역할이 플레이어에게 갔는지 들키지 않는다
        (원나잇 정석 진행과 동일). 튜토리얼 모드도 동일하게 덱 구성을 따르므로,
        이번 판에 선택하지 않은 역할은 소개되지 않는다.
        """
        role = PHASE_TO_ROLE[phase]
        return role.value in self.state.deck_roles

    def _make_state_update(self) -> WSMessage:
        payload = self.state.to_dict()
        # 이 페이즈가 몇 초 뒤에 저절로 넘어가는지 함께 보낸다.
        #
        # 화면의 카운트다운이 이 숫자를 자기 파일에 복사해 갖고 있었는데, 백엔드
        # 시간만 바꾸고 화면 쪽을 못 바꾸면 숫자가 0이 되어도 단계가 안 넘어가거나
        # 그 반대가 된다. 실제로 어긋난 적이 있다. 숫자의 주인은 타이머를 가진
        # 쪽이므로 여기서 실어 보낸다.
        payload["phase_duration"] = self._phase_duration()
        return WSMessage(
            msg_type=MsgType.STATE_UPDATE.value,
            payload=payload,
            state_version=self.state.state_version,
        )

    def _phase_duration(self) -> int | None:
        """현재 페이즈의 자동 전이까지 걸리는 초. 타이머가 없으면 None."""
        phase = WerewolfPhase(self.state.phase)
        if self._practice_mode:
            # 튜토리얼은 안내 TTS가 끝난 뒤 화면이 전이를 주도한다. 고정 시간이 없다.
            return None
        if phase == WerewolfPhase.NIGHT_START:
            return NIGHT_START_DURATION
        if phase in ACTIVE_NIGHT_PHASES:
            return ACTIVE_PHASE_TIMEOUT
        if phase in NIGHT_PHASES:
            return PASSIVE_PHASE_DURATION
        return None

    def _advance_to_next_phase(self) -> list[WSMessage]:
        """현재 페이즈에서 다음 페이즈로 전이한다."""
        current = WerewolfPhase(self.state.phase)

        if current in (WerewolfPhase.NIGHT_START, *NIGHT_PHASES):
            search_from = (
                -1
                if current == WerewolfPhase.NIGHT_START
                else NIGHT_PHASES.index(current)
            )
            for next_phase in NIGHT_PHASES[search_from + 1:]:
                if self._night_phase_included(next_phase):
                    return self._enter_phase(next_phase)
            return self._enter_phase(WerewolfPhase.DAY_DISCUSSION)

        if current == WerewolfPhase.DAY_DISCUSSION:
            return self._enter_phase(WerewolfPhase.VOTE_COUNTDOWN)

        if current in (WerewolfPhase.VOTE_COUNTDOWN, WerewolfPhase.VOTE):
            # 역할을 모르므로 승패는 판정하지 않는다. 최다 득표자만 확정해 발표하고,
            # 카드 공개와 승패 판단은 플레이어들이 직접 한다.
            self.state.executed = find_executed(self.state)
            # Benchmark hook: 정상 게임 종료.
            try:
                import time as _t

                from benchmarks.common.trace_setup import bench_log
                bench_log().info("game_end werewolf normal %.6f", _t.time())
            except Exception:
                pass
            return self._enter_phase(WerewolfPhase.RESULT)

        return []

    def _enter_phase(self, phase: WerewolfPhase) -> list[WSMessage]:
        """페이즈 진입: state 업데이트 + FusionContext 발송."""
        # 새 페이즈 진입 시 이전 타이머 취소
        if self._active_timer_task and not self._active_timer_task.done():
            self._active_timer_task.cancel()
            self._active_timer_task = None
        self.state.phase = phase.value
        self.state.state_version += 1
        msgs: list[WSMessage] = [self._make_state_update()]

        if phase in (
            WerewolfPhase.NIGHT_WEREWOLF,
            WerewolfPhase.NIGHT_MINION,
            WerewolfPhase.NIGHT_MASON,
        ):
            # 패시브 역할: 일반 모드는 PASSIVE_PHASE_DURATION 초 후 자동 전이.
            # 튜토리얼 모드는 안내 TTS를 끝까지 재생하도록 프론트가 start_now로 전이를
            # 주도하므로 백엔드 고정 타이머를 걸지 않는다(마지막 역할 TTS 잘림 방지).
            if not self._practice_mode:
                self._passive_timer_task = asyncio.create_task(
                    self._run_passive_timer(phase)
                )
            msgs.append(
                WSMessage.make_fusion_context(
                    self.get_fusion_context(),
                    state_version=self.state.state_version,
                )
            )
            return msgs

        if phase == WerewolfPhase.DAY_DISCUSSION:
            self._timer_task = asyncio.create_task(self._run_timer())

        elif phase == WerewolfPhase.VOTE_COUNTDOWN:
            # 카운트다운은 진입 즉시 시작하지 않는다. 프론트가 안내 TTS를 끝까지 재생한 뒤
            # VOTE_COUNTDOWN_START 입력으로 시작을 주도한다(페이지 전환 직후 숫자가 곧바로
            # 줄어 지목 타이밍을 놓치는 문제 방지). 준비 구간(countdown_remaining=None)에도
            # 비전/수동 지목은 계속 반영된다.
            self.state.votes_locked = False
            self.state.countdown_remaining = None
            for p in self.state.players:
                p.voted_for = None

        elif phase == WerewolfPhase.RESULT:
            return msgs  # 종료 상태; FusionContext 불필요

        # 액티브 야간 역할: OK 사인 우선, ACTIVE_PHASE_TIMEOUT 초 경과 시 자동 전이.
        # 튜토리얼 모드는 폴백 타이머를 끄고, 프론트가 안내 TTS 종료 후 start_now로
        # 전이를 주도하게 해 TTS가 끊기지 않도록 한다.
        if phase in ACTIVE_NIGHT_PHASES and not self._practice_mode:
            self._active_timer_task = asyncio.create_task(
                self._run_active_timer(phase)
            )

        msgs.append(
            WSMessage.make_fusion_context(
                self.get_fusion_context(),
                state_version=self.state.state_version,
            )
        )
        return msgs

    # ── Event handlers ──────────────────────────────────────────────────────────

    def _handle_vote_point(self, event: GameEvent) -> list[WSMessage]:
        if WerewolfPhase(self.state.phase) not in (
            WerewolfPhase.VOTE_COUNTDOWN,
            WerewolfPhase.VOTE,
        ):
            return []
        actor_id = event.actor_id
        target_id = event.data.get("target_id")
        if not actor_id or not target_id:
            return []
        messages = self._record_vote(actor_id, target_id)
        if messages:
            # Benchmark hook: 비전이 인식한 투표 (vote_recognition 분모).
            try:
                from benchmarks.common.trace_setup import bench_log
                bench_log().info("vote_cast -")
            except Exception:
                pass
        return messages

    def _handle_gesture_confirmed(self) -> list[WSMessage]:
        """OK 사인으로 야간 역할 페이즈를 진행한다.

        패시브·액티브 구분 없이 모든 야간 "역할" 페이즈에서 유효하다. 역할을 모르므로
        누가 보낸 신호인지는 검증하지 않는다 — 눈을 뜨고 있는 사람만 신호를 보낼 수
        있다는 게임 규칙 자체가 게이트 역할을 한다.

        NIGHT_START는 제외한다. get_fusion_context()에서 이미 OK 사인을 받지 않지만,
        컨텍스트 갱신(백엔드 스레드)과 프레임 처리(비전 스레드)가 별개라 전환 직전
        프레임에서 만들어진 이벤트가 뒤늦게 도착할 수 있어 여기서도 막는다.
        """
        current = WerewolfPhase(self.state.phase)
        if current not in NIGHT_PHASES:
            return []
        for task_attr in ("_passive_timer_task", "_active_timer_task"):
            task = getattr(self, task_attr)
            if task and not task.done():
                task.cancel()
                setattr(self, task_attr, None)
        return self._advance_to_next_phase()

    def _record_vote(self, voter_id: str, target_id: str) -> list[WSMessage]:
        """비전 이벤트 경로. votes_locked이면 거부해 카운트다운 후 lock을 결정적으로 유지."""
        if self.state.votes_locked:
            return []
        return self._set_vote(voter_id, target_id)

    def _set_vote(self, voter_id: str, target_id: str) -> list[WSMessage]:
        """voted_for 설정 공통 로직. 전이 없음 — VOTE_RESULT_CONFIRM에서만 전이."""
        try:
            voter = self.state.get_player(voter_id)
            self.state.get_player(target_id)  # target 존재 검증
        except KeyError:
            return []
        voter.voted_for = target_id
        self.state.state_version += 1
        return [self._make_state_update()]

    # ── Input handlers ──────────────────────────────────────────────────────────

    def _handle_add_30_sec(self) -> list[WSMessage]:
        if WerewolfPhase(self.state.phase) != WerewolfPhase.DAY_DISCUSSION:
            return []
        self.state.timer_remaining += 30
        self.state.state_version += 1
        return [self._make_state_update()]

    def _handle_start_now(self) -> list[WSMessage]:
        current = WerewolfPhase(self.state.phase)
        if current in PASSIVE_NIGHT_PHASES:
            return self._advance_to_next_phase()
        if current in ACTIVE_NIGHT_PHASES:
            if self._active_timer_task and not self._active_timer_task.done():
                self._active_timer_task.cancel()
                self._active_timer_task = None
            return self._advance_to_next_phase()
        if current == WerewolfPhase.DAY_DISCUSSION:
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
                self._timer_task = None
            return self._advance_to_next_phase()
        return []

    def _handle_vote_player(self, player_id: str | None, data: dict) -> list[WSMessage]:
        """수동 보정 경로. votes_locked이어도 허용 (확인 화면 오인식 보정용)."""
        if WerewolfPhase(self.state.phase) not in (
            WerewolfPhase.VOTE_COUNTDOWN,
            WerewolfPhase.VOTE,
        ):
            return []
        if not player_id:
            return []
        target_id = data.get("target_id")
        if not target_id:
            return []
        messages = self._set_vote(player_id, target_id)
        if messages:
            # Benchmark hook: 사용자의 투표 오인식 수동 정정 = 인식 실패 신호.
            try:
                from benchmarks.common.trace_setup import bench_log
                bench_log().info("vote_correction -")
            except Exception:
                pass
        return messages

    def _handle_vote_result_confirm(self) -> list[WSMessage]:
        """투표 결과 확인 화면에서 최종 확정. votes_locked 상태에서만 유효."""
        if WerewolfPhase(self.state.phase) != WerewolfPhase.VOTE_COUNTDOWN:
            return []
        if not self.state.votes_locked:
            return []
        return self._advance_to_next_phase()

    def _handle_vote_countdown_start(self) -> list[WSMessage]:
        """안내 TTS 종료 후 프론트가 호출 — 5→0 카운트다운을 시작한다.
        이미 시작했거나 잠긴 상태면 중복 신호(워치독+TTS 종료 동시 등)를 무시한다."""
        if WerewolfPhase(self.state.phase) != WerewolfPhase.VOTE_COUNTDOWN:
            return []
        if self.state.countdown_remaining is not None or self.state.votes_locked:
            return []
        self.state.countdown_remaining = VOTE_COUNTDOWN_SECONDS
        self.state.state_version += 1
        self._active_timer_task = asyncio.create_task(self._run_vote_countdown())
        return [self._make_state_update()]

    # ── Timer ───────────────────────────────────────────────────────────────────

    async def _run_timer(self) -> None:
        """DAY_DISCUSSION 1초 타이머. 만료 시 VOTE_COUNTDOWN으로 전이."""
        try:
            while self.state.timer_remaining > 0:
                await asyncio.sleep(1)
                if WerewolfPhase(self.state.phase) != WerewolfPhase.DAY_DISCUSSION:
                    return
                self.state.timer_remaining -= 1
                self.state.state_version += 1
                await self._broadcast(self._make_state_update())

            if WerewolfPhase(self.state.phase) == WerewolfPhase.DAY_DISCUSSION:
                for msg in self._advance_to_next_phase():
                    await self._broadcast(msg)
        except asyncio.CancelledError:
            pass

    async def _run_vote_countdown(self) -> None:
        """VOTE_COUNTDOWN 5→0 카운트다운 → VOTE_LOCK_GRACE 유예 → votes_locked=True."""
        try:
            while (
                self.state.countdown_remaining is not None
                and self.state.countdown_remaining > 0
            ):
                await asyncio.sleep(1)
                if WerewolfPhase(self.state.phase) != WerewolfPhase.VOTE_COUNTDOWN:
                    return
                self.state.countdown_remaining -= 1
                self.state.state_version += 1
                await self._broadcast(self._make_state_update())

            if WerewolfPhase(self.state.phase) != WerewolfPhase.VOTE_COUNTDOWN:
                return

            # 유예 구간: 이 0.5초 동안도 비전 지목은 계속 반영됨
            await asyncio.sleep(VOTE_LOCK_GRACE)

            if WerewolfPhase(self.state.phase) != WerewolfPhase.VOTE_COUNTDOWN:
                return

            self.state.votes_locked = True
            self.state.countdown_remaining = None
            self.state.state_version += 1
            await self._broadcast(self._make_state_update())
        except asyncio.CancelledError:
            pass

    async def _run_passive_timer(
        self,
        phase: WerewolfPhase,
        duration: float | None = None,
    ) -> None:
        """패시브 안내 화면을 duration 초 표시 후 다음 페이즈로 전이.

        duration 생략 시 PASSIVE_PHASE_DURATION(역할 안내 기본값)을 쓴다.
        """
        try:
            await asyncio.sleep(
                PASSIVE_PHASE_DURATION if duration is None else duration
            )
            if WerewolfPhase(self.state.phase) == phase:
                self.state.state_version += 1
                for msg in self._advance_to_next_phase():
                    await self._broadcast(msg)
        except asyncio.CancelledError:
            pass

    async def _run_active_timer(self, phase: WerewolfPhase) -> None:
        """액티브 역할 카드 감지 대기. ACTIVE_PHASE_TIMEOUT 초 경과 시 강제 전이."""
        try:
            await asyncio.sleep(ACTIVE_PHASE_TIMEOUT)
            if WerewolfPhase(self.state.phase) == phase:
                self.state.state_version += 1
                for msg in self._advance_to_next_phase():
                    await self._broadcast(msg)
        except asyncio.CancelledError:
            pass

