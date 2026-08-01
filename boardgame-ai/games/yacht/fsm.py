"""요트다이스 게임 FSM."""

from __future__ import annotations

import logging
from typing import Any

from core.constants import MsgType
from core.envelope import WSMessage
from core.events import FusionContext, GameEvent
from core.models import Player
from games.base_fsm import BaseFSM
from games.yacht.scoring import (
    UPPER_BONUS_SCORE,
    UPPER_BONUS_THRESHOLD,
    calculate_score,
    upper_subtotal,
)
from games.yacht.state import YachtEventType, YachtGameState, YachtInputType, YachtPhase

logger = logging.getLogger(__name__)

_CATEGORY_TTS_LABELS: dict[str, str] = {
    "ones": "에이스",
    "twos": "투",
    "threes": "쓰리",
    "fours": "포",
    "fives": "파이브",
    "sixes": "식스",
    "choice": "초이스",
    "four_of_a_kind": "포카드",
    "full_house": "풀 하우스",
    "small_straight": "스몰 스트레이트",
    "large_straight": "라지 스트레이트",
    "yacht": "요트",
}

# 굴림 축하 대상과 그 강도.
#
# 순서가 곧 우선순위다. 한 굴림이 여러 조합을 만족할 수 있으므로(야찌는
# 포카드이기도 하고 라지스트레이트는 스몰스트레이트이기도 하다) 더 희귀한
# 것부터 본다. frozenset을 쓰면 순회 순서가 비결정적이라 같은 눈에도 다른
# 축하가 떴다.
#
# tier는 화면이 연출 크기를 고르는 데 쓴다. 다 똑같이 터뜨리면 야찌가 스몰
# 스트레이트와 같은 무게가 되어 아무것도 특별하지 않다.
_HAND_TIERS: tuple[tuple[str, str], ...] = (
    ("yacht", "legendary"),
    ("large_straight", "epic"),
    ("four_of_a_kind", "great"),
    ("full_house", "good"),
    ("small_straight", "nice"),
)

# 조명이 크게 반응할 족보. 굴림 축하 대상보다 좁다 — 요트는 조명이 곧 인식
# 조명이라 자주 흔들 수 없다.
_HIGHLIGHT_CATEGORIES: frozenset[str] = frozenset({"yacht", "large_straight"})

# 선두 역전을 사건으로 칠 최소 진행도 (채운 족보 수).
#
# 초반에는 순위가 매 턴 뒤집힌다 — 아무나 5점만 넣어도 1위다. 그걸 전부
# 역전이라고 연출하면 의미가 닳는다. 후반의 뒤집기만 사건으로 친다.
_LEAD_CHANGE_MIN_FILLED = 7

# 모달·조명·TTS가 공유하는 연출 길이. 사건의 크기에 비례한다.
#
# 일반 턴은 모달 없이 화면 안에서만 처리하므로 짧다. 한 판에 36턴이라
# 여기서 몇백 ms가 그대로 루즈함이 된다.
_CUE_DURATION_MS: dict[str, int] = {
    "normal": 1600,
    "zero": 1400,        # 아쉬움은 짧게 — 실패를 길게 보여줄 이유가 없다
    # 순위표가 이전 순위를 보여준 뒤 미끄러져야 해서 다른 것보다 길다.
    "lead_change": 3600,
    # 특별 조합은 주사위가 멈춘 순간에 이미 크게 축하했다. 여기서는 점수만
    # 확인시켜주면 되므로 짧게 끝낸다.
    "highlight": 1800,
}
_GAME_FINISH_CUE_DURATION_MS = 4000

# 굴림 축하. 조명이 관여하지 않으므로 인식 예산에 묶이지 않는다 — 화면만 쓰는
# 연출이다. 다만 아직 점수를 고르기 전이라 길면 방해가 되므로, 흔한 조합일수록
# 짧게 끝낸다.
_HAND_TIER_DURATION_MS: dict[str, int] = {
    "legendary": 2800,
    "epic": 2400,
    "great": 1800,
    "good": 1500,
    "nice": 1200,
}

# 상단 보너스 확정. 게임 내내 쌓아온 것이 한 번에 터지는 순간이라 넉넉히 준다.
_BONUS_CUE_DURATION_MS = 2600


def _ranking(players: list[Any]) -> dict[str, int]:
    """player_id → 1부터 시작하는 순위. 동점은 같은 순위를 공유한다."""
    distinct_totals = sorted({p.total for p in players}, reverse=True)
    rank_of_total = {total: index + 1 for index, total in enumerate(distinct_totals)}
    return {p.player_id: rank_of_total[p.total] for p in players}


def _with_bonus(messages: list[WSMessage], bonus_cue: WSMessage | None) -> list[WSMessage]:
    """보너스 큐를 득점 큐 뒤에 끼워 넣는다.

    순서가 곧 연출 순서다 — "+18점" 다음에 "보너스 +35점"이 와야 쌓인 것이
    터지는 흐름이 된다. 반대로 오면 보너스가 어디서 나왔는지 알 수 없다.
    """
    if bonus_cue is None:
        return messages
    # 마지막은 FusionContext라 그 앞에 넣는다.
    return [*messages[:-1], bonus_cue, messages[-1]]


def _sole_leader(players: list[Any]) -> Any | None:
    """단독 선두. 공동 1위면 None — 뺏을 자리가 없다는 뜻이다."""
    best = max(p.total for p in players)
    leaders = [p for p in players if p.total == best]
    return leaders[0] if len(leaders) == 1 else None


class YachtFSM(BaseFSM):
    def __init__(
        self,
        players: list[Player | str | dict[str, Any]],
    ) -> None:
        self.state = YachtGameState.new(players)

    def _emit_fusion_context(self) -> WSMessage:
        """현재 FusionContext를 WSMessage로 반환. 세션이 가로채 브리지로 전달."""
        return WSMessage.make_fusion_context(self.get_fusion_context(), self.state.state_version)

    def start(self) -> list[WSMessage]:
        self.state.phase = YachtPhase.AWAITING_ROLL.value
        self.state.state_version += 1
        self.state.last_message = f"{self.state.current_player.playername}님, 주사위를 굴려주세요."
        return [
            self._make_state_update(),
            self._emit_fusion_context(),
        ]

    def handle_event(self, event: GameEvent) -> list[WSMessage]:
        if event.event_type == YachtEventType.ROLL_CONFIRMED.value:
            return self._handle_roll_confirmed(event)
        if event.event_type == YachtEventType.ROLL_UNREADABLE.value:
            return self._handle_roll_unreadable(event)
        if event.event_type == YachtEventType.DICE_ESCAPED.value:
            return self._warn_and_keep_roll_phase(
                "주사위가 트레이 밖으로 나갔습니다. 다시 굴려주세요."
            )
        if event.event_type in (
            YachtEventType.RULE_VIOLATION.value,
            YachtEventType.RULE_VIOLATION_LOWER.value,
        ):
            return self._warn_and_keep_roll_phase(
                f"지금은 {self.state.current_player.playername}님 차례입니다.",
            )
        return []

    def handle_input(
        self,
        input_type: str,
        data: dict,
        player_id: str | None = None,
    ) -> list[WSMessage]:
        if input_type == YachtInputType.DICE_KEEP_SELECTED.value:
            return self._handle_keep_selected(data)
        if input_type == YachtInputType.DICE_REROLL_REQUESTED.value:
            return self._handle_reroll_requested(data)
        if input_type == YachtInputType.SCORE_CATEGORY_SELECTED.value:
            return self._handle_score_category(data, player_id)
        if input_type == YachtInputType.RESOLVE_UNREADABLE_ROLL.value:
            return self._handle_unreadable_resolution(data)
        return []

    def get_fusion_context(self) -> FusionContext:
        phase = YachtPhase(self.state.phase)
        active_player = (
            None if phase == YachtPhase.GAME_END else self.state.current_player.player_id
        )
        expected_events: list[str] = []
        reject_events: list[str] = []

        if phase in (YachtPhase.AWAITING_ROLL, YachtPhase.AWAITING_KEEP):
            expected_events = [
                YachtEventType.ROLL_CONFIRMED.value,
                YachtEventType.ROLL_UNREADABLE.value,
                YachtEventType.DICE_ESCAPED.value,
                YachtEventType.RULE_VIOLATION.value,
                YachtEventType.RULE_VIOLATION_LOWER.value,
            ]
        else:
            reject_events = [
                YachtEventType.ROLL_CONFIRMED.value,
                YachtEventType.ROLL_UNREADABLE.value,
                YachtEventType.DICE_ESCAPED.value,
            ]

        return FusionContext(
            fsm_state=phase.value,
            game_type="yacht",
            active_player=active_player,
            allowed_actors=[active_player] if active_player else [],
            expected_events=expected_events,
            reject_events=reject_events,
            valid_targets={"categories": self.state.available_categories},
            zones={},
            anchors={},
            params={},
        )

    def get_state_dict(self) -> dict:
        return self.state.to_dict()

    def restore_state(
        self,
        state: YachtGameState,
        message: str | None = None,
    ) -> list[WSMessage]:
        restored_version = max(self.state.state_version, state.state_version) + 1
        self.state = state
        self.state.state_version = restored_version
        if message is not None:
            self.state.last_message = message
        return self._state_context_messages()

    def _handle_roll_confirmed(self, event: GameEvent) -> list[WSMessage]:
        if self.state.phase not in (
            YachtPhase.AWAITING_ROLL.value,
            YachtPhase.AWAITING_KEEP.value,
        ):
            return []
        if self.state.roll_count >= 3:
            return []
        if not self._is_current_actor(event.actor_id):
            return self._warn_and_keep_roll_phase(
                f"지금은 {self.state.current_player.playername}님 차례입니다.",
            )

        dice_values = event.data.get("dice_values", [])
        if len(dice_values) != 5 or any(v is None for v in dice_values):
            unreadable = [i for i, value in enumerate(dice_values) if value is None]
            return self._record_unreadable_roll(dice_values, unreadable)

        sorted_values, sorted_keep_mask = self._sort_dice_with_keep(
            [int(v) for v in dice_values],
            self._normalize_keep_mask(event.data.get("keep_mask")),
        )
        self.state.dice_values = sorted_values
        self.state.keep_mask = sorted_keep_mask
        self.state.roll_count += 1
        self.state.unreadable_roll = None
        self.state.phase = (
            YachtPhase.AWAITING_SCORE.value
            if self.state.roll_count >= 3
            else YachtPhase.AWAITING_KEEP.value
        )
        self.state.last_message = self._roll_message()
        self.state.state_version += 1

        messages = self._state_context_messages()
        achieved = self._make_hand_cue()
        if achieved is not None:
            messages.insert(1, achieved)
        return messages

    def _handle_roll_unreadable(self, event: GameEvent) -> list[WSMessage]:
        if self.state.phase not in (
            YachtPhase.AWAITING_ROLL.value,
            YachtPhase.AWAITING_KEEP.value,
        ):
            return []
        if self.state.roll_count >= 3:
            return []
        if not self._is_current_actor(event.actor_id):
            return []
        dice_values = list(event.data.get("dice_values", []))
        unknown_indices = list(event.data.get("unknown_indices", []))
        return self._record_unreadable_roll(dice_values, unknown_indices)

    def _handle_keep_selected(self, data: dict) -> list[WSMessage]:
        if self.state.phase not in (
            YachtPhase.AWAITING_KEEP.value,
            YachtPhase.AWAITING_SCORE.value,
        ):
            return []
        self.state.keep_mask = self._normalize_keep_mask(data.get("keep_mask"))
        self.state.state_version += 1
        return [self._make_state_update()]

    def _handle_reroll_requested(self, data: dict) -> list[WSMessage]:
        if self.state.phase != YachtPhase.AWAITING_KEEP.value:
            return []
        if self.state.roll_count >= 3:
            return []
        if "keep_mask" in data:
            self.state.keep_mask = self._normalize_keep_mask(data.get("keep_mask"))
        self.state.phase = YachtPhase.AWAITING_ROLL.value
        self.state.state_version += 1
        self.state.last_message = f"{self.state.current_player.playername}님, 다시 굴려주세요."
        return self._state_context_messages()

    def _handle_score_category(self, data: dict, player_id: str | None) -> list[WSMessage]:
        if self.state.phase not in (
            YachtPhase.AWAITING_KEEP.value,
            YachtPhase.AWAITING_SCORE.value,
        ):
            return []
        if player_id is not None and player_id != self.state.current_player.player_id:
            return []

        category = data.get("category")
        if not category or category not in self.state.available_categories:
            return [
                WSMessage.make_error(
                    "INVALID_SCORE_CATEGORY",
                    "선택할 수 없는 점수 카테고리입니다.",
                    self.state.state_version,
                )
            ]

        try:
            score = (
                int(data["score"])
                if "score" in data
                else calculate_score(category, self.state.dice_values)
            )
        except (TypeError, ValueError) as exc:
            return [WSMessage.make_error("INVALID_DICE_VALUES", str(exc), self.state.state_version)]

        current_player = self.state.current_player
        # 순위 변동은 점수를 쓰기 전에 찍어둬야 알 수 있다.
        ranks_before = _ranking(self.state.players)
        leader_before = _sole_leader(self.state.players)
        bonus_before = upper_subtotal(current_player.scores) >= UPPER_BONUS_THRESHOLD

        current_player.scores[str(category)] = score
        scorer_name = current_player.playername
        score_label = _CATEGORY_TTS_LABELS.get(str(category), str(category))
        self.state.state_version += 1

        moment = self._describe_moment(
            scorer=current_player,
            category=str(category),
            score=score,
            ranks_before=ranks_before,
            leader_before=leader_before,
        )
        # 상단 보너스는 방금 넣은 점수 때문에 확정될 수 있다. 게임 내내 쌓아온
        # 것이 한 번에 붙는 순간이라 득점과 별개의 사건으로 알린다.
        bonus_cue = (
            None
            if bonus_before or upper_subtotal(current_player.scores) < UPPER_BONUS_THRESHOLD
            else WSMessage.make_cue(
                cue="yacht_bonus_achieved",
                payload={
                    "scorer_id": current_player.player_id,
                    "scorer_name": current_player.playername,
                    "score": UPPER_BONUS_SCORE,
                    "upper_subtotal": upper_subtotal(current_player.scores),
                    "threshold": UPPER_BONUS_THRESHOLD,
                    "duration_ms": _BONUS_CUE_DURATION_MS,
                },
                state_version=self.state.state_version,
            )
        )

        if self.state.is_final_round_complete:
            self.state.finish_game()
            self.state.state_version += 1
            self.state.last_message = (
                f"{scorer_name}님 {score_label} {score}점입니다. 게임이 종료되었습니다."
            )
            # Benchmark hook: 정상 게임 종료 (completion_rate 측정용).
            try:
                import time as _t

                from benchmarks.common.trace_setup import bench_log
                bench_log().info("game_end yacht normal %.6f", _t.time())
            except Exception:
                pass
            return _with_bonus(
                [
                    self._make_state_update(),
                    self._make_score_cue(
                        cue="yacht_game_finish",
                        scorer=current_player,
                        score_label=score_label,
                        score=score,
                        next_player=None,
                        duration_ms=_GAME_FINISH_CUE_DURATION_MS,
                        moment=moment,
                    ),
                    self._emit_fusion_context(),
                ],
                bonus_cue,
            )

        self.state.advance_player()
        self.state.phase = YachtPhase.AWAITING_ROLL.value
        self.state.last_message = (
            f"{scorer_name}님 {score_label} {score}점입니다. "
            f"{self.state.current_player.playername}님 차례입니다."
        )
        return _with_bonus(
            [
                self._make_state_update(),
                self._make_score_cue(
                    cue="yacht_turn_transition",
                    scorer=current_player,
                    score_label=score_label,
                    score=score,
                    next_player=self.state.current_player.playername,
                    duration_ms=_CUE_DURATION_MS[moment["variant"]],
                    moment=moment,
                ),
                self._emit_fusion_context(),
            ],
            bonus_cue,
        )

    def _make_hand_cue(self) -> WSMessage | None:
        """방금 굴린 눈이 특별 조합이면 그 순간을 알린다.

        축하는 칸을 고른 뒤가 아니라 주사위가 멈춘 순간에 터져야 자연스럽다.
        칸 선택은 그 뒤에 오는 사무적인 절차고, 짜릿한 건 눈이 맞아떨어진 순간이다.

        같은 턴에 같은 조합이 두 번 나와도 두 번 다 알린다 — 세 번 굴릴 수 있고,
        다시 맞춘 것도 그 나름의 순간이다.

        **조명은 이 큐를 건드리지 않는다.** 매핑 테이블에 이름이 없으면
        LightController가 그냥 무시하므로 별도 분기가 필요 없다. 굴림 구간은
        주사위 인식이 걸린 곳이라 조명이 흔들려선 안 되고, 연출은 화면이 맡는다.
        조명은 점수를 확정하는 순간에만 움직인다.
        """
        available = self.state.available_categories
        for category, tier in _HAND_TIERS:
            # 이미 채운 칸이면 축하할 것이 없다. "요트!"라고 띄워놓고 다른 칸에
            # 넣게 하는 것은 축하가 아니라 약올리기다.
            if category not in available:
                continue
            score = calculate_score(category, self.state.dice_values)
            if score <= 0:
                continue
            return WSMessage.make_cue(
                cue="yacht_hand_achieved",
                payload={
                    "scorer_id": self.state.current_player.player_id,
                    "scorer_name": self.state.current_player.playername,
                    "category": category,
                    "category_label": _CATEGORY_TTS_LABELS.get(category, category),
                    "score": score,
                    "tier": tier,
                    "duration_ms": _HAND_TIER_DURATION_MS[tier],
                },
                state_version=self.state.state_version,
            )
        return None

    def _describe_moment(
        self,
        scorer: Player,
        category: str,
        score: int,
        ranks_before: dict[str, int],
        leader_before: Player | None,
    ) -> dict[str, Any]:
        """이 득점이 어떤 종류의 사건인지 판정한다.

        연출의 크기를 정하는 것은 점수 숫자가 아니라 이 판정이다. 한 판에
        36턴이라 모두를 크게 연출하면 아무것도 특별하지 않고 게임만 늘어진다.
        대부분은 normal로 떨어져 화면 안에서 조용히 처리된다.
        """
        ranks_after = _ranking(self.state.players)
        rank_before = ranks_before[scorer.player_id]
        rank_after = ranks_after[scorer.player_id]

        # 특별 족보는 "칸을 골랐다"가 아니라 "실제로 달성했다"여야 사건이다.
        # 요트 칸에 0점을 버리는 것은 축하가 아니라 그 반대다.
        is_highlight = category in _HIGHLIGHT_CATEGORIES and score > 0

        # 순위가 오르기만 하면 역전이다. 1등을 뺏는 것만 역전이라고 하면
        # 3등에서 2등으로 올라간 사람은 아무 일도 없는 것처럼 지나가고,
        # 연출이 특정 플레이어에게만 붙는 것처럼 보인다.
        #
        # 0점은 총점을 못 올리므로 남을 앞지를 수 없다. 역전과 자연히 배타적이다.
        overtook = (
            rank_after < rank_before
            and len(scorer.scores) >= _LEAD_CHANGE_MIN_FILLED
        )
        took_lead = overtook and rank_after == 1

        # 역전이 특별 조합보다 앞선다. 조합은 주사위가 멈춘 순간에 이미 크게
        # 축하했으므로, 확정 시점에 더 할 말이 있는 쪽은 순위 변동이다.
        if score <= 0:
            variant = "zero"
        elif overtook:
            variant = "lead_change"
        elif is_highlight:
            variant = "highlight"
        else:
            variant = "normal"

        return {
            "category": category,
            "variant": variant,
            "is_highlight": is_highlight,
            "overtook": overtook,
            "took_lead": took_lead,
            "rank_before": rank_before,
            "rank_after": rank_after,
            "previous_leader": leader_before.playername if leader_before else None,
            # 순위표가 자리를 바꾸는 연출에 필요하다. 3등에서 2등도 역전이므로
            # 득점자만이 아니라 전원의 이동을 보낸다.
            "standings": [
                {
                    "player_id": p.player_id,
                    "playername": p.playername,
                    "total": p.total,
                    "rank_before": ranks_before[p.player_id],
                    "rank_after": ranks_after[p.player_id],
                }
                for p in self.state.players
            ],
        }

    def _make_score_cue(
        self,
        cue: str,
        scorer: Player,
        score_label: str,
        score: int,
        next_player: str | None,
        duration_ms: int,
        moment: dict[str, Any],
    ) -> WSMessage:
        """득점 순간을 구조화된 payload로 발행.

        같은 정보가 last_message에도 한국어 문장으로 들어가지만, 그 문장은
        TTS용이라 연출이 쓸 수 없다. 모달·조명은 이 payload를 읽는다.

        프론트가 current_player 변화를 diff해서 턴 전환을 추론하던 방식을
        대체한다. diff 추론은 재연결 시 상태 재동기화를 턴 전환으로 오인했고,
        백엔드에서 도는 조명은 애초에 그 순간을 알 방법이 없었다.
        """
        return WSMessage.make_cue(
            cue=cue,
            payload={
                "scorer_id": scorer.player_id,
                "scorer_name": scorer.playername,
                "category": moment.get("category", ""),
                "category_label": score_label,
                "score": score,
                "next_player": next_player,
                "duration_ms": duration_ms,
                # 연출의 크기를 정하는 값. 모달 종류와 조명 Cue 변형이 여기서 갈린다.
                "variant": moment["variant"],
                "is_highlight": moment["is_highlight"],
                "overtook": moment["overtook"],
                "took_lead": moment["took_lead"],
                "rank_before": moment["rank_before"],
                "rank_after": moment["rank_after"],
                "previous_leader": moment["previous_leader"],
                "standings": moment["standings"],
            },
            state_version=self.state.state_version,
        )

    def _handle_unreadable_resolution(self, data: dict) -> list[WSMessage]:
        if self.state.phase != YachtPhase.AWAITING_SCORE.value or not self.state.unreadable_roll:
            return []
        dice_values = data.get("dice_values")
        event = GameEvent(
            event_type=YachtEventType.ROLL_CONFIRMED.value,
            actor_id=self.state.current_player.player_id,
            confidence=1.0,
            frame_id=-1,
            data={"dice_values": dice_values, "keep_mask": self.state.keep_mask},
        )
        self.state.phase = YachtPhase.AWAITING_ROLL.value
        return self._handle_roll_confirmed(event)

    def _record_unreadable_roll(
        self, dice_values: list[Any], unknown_indices: list[Any]
    ) -> list[WSMessage]:
        self.state.unreadable_roll = {
            "dice_values": list(dice_values),
            "unknown_indices": [int(i) for i in unknown_indices],
        }
        self.state.phase = YachtPhase.AWAITING_SCORE.value
        self.state.last_message = "읽히지 않은 주사위 값이 있습니다. 화면에서 값을 입력해주세요."
        self.state.state_version += 1
        return self._state_context_messages()

    def _warn_and_keep_roll_phase(self, message: str) -> list[WSMessage]:
        self.state.last_message = message
        self.state.state_version += 1
        return [self._make_state_update()]

    def _is_current_actor(self, actor_id: str | None) -> bool:
        """굴린 사람이 현재 차례 플레이어인가.

        actor_id가 None이면 비전이 굴린 사람을 특정하지 못한 경우다. 이때는
        현재 플레이어의 굴림인데 손 player_id가 미확정이었을 가능성이 높으므로
        통과시킨다 (정상 굴림을 차례 위반으로 오인하지 않기 위함).
        actor_id가 다른 플레이어로 명확히 잡힌 경우에만 차례 위반으로 본다.
        """
        return actor_id in (None, self.state.current_player.player_id)

    def _roll_message(self) -> str:
        values = ", ".join(str(v) for v in self.state.dice_values)
        if self.state.phase == YachtPhase.AWAITING_SCORE.value:
            return f"주사위 결과는 {values}입니다. 점수 칸을 선택해주세요."
        remaining_text = {2: "두 번", 1: "한 번"}.get(max(0, 3 - self.state.roll_count), "0번")
        return f"기회 {remaining_text} 남았습니다. 다시 굴리거나 점수 칸을 선택해주세요."

    def _normalize_keep_mask(self, keep_mask: Any) -> list[bool]:
        if not isinstance(keep_mask, list) or len(keep_mask) != 5:
            return [False] * 5
        return [bool(v) for v in keep_mask]

    def _sort_dice_with_keep(
        self,
        dice_values: list[int],
        keep_mask: list[bool],
    ) -> tuple[list[int], list[bool]]:
        pairs = sorted(
            zip(dice_values, keep_mask, strict=True),
            key=lambda pair: pair[0],
        )
        return [value for value, _ in pairs], [kept for _, kept in pairs]

    def _state_context_messages(self) -> list[WSMessage]:
        return [
            self._make_state_update(),
            self._emit_fusion_context(),
        ]

    def _make_state_update(self) -> WSMessage:
        return WSMessage(
            msg_type=MsgType.STATE_UPDATE.value,
            payload=self.state.to_dict(),
            state_version=self.state.state_version,
        )
