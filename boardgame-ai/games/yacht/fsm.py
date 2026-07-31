"""요트다이스 게임 FSM."""

from __future__ import annotations

import logging
from typing import Any

from core.constants import MsgType
from core.envelope import WSMessage
from core.events import FusionContext, GameEvent
from core.models import Player
from games.base_fsm import BaseFSM
from games.yacht.scoring import calculate_score
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

# 달성 자체가 사건인 족보. 연출을 길게 가져간다.
_HIGHLIGHT_CATEGORIES: frozenset[str] = frozenset({"yacht", "large_straight"})

# 모달·조명·TTS가 공유하는 연출 길이.
# 일반 턴 전환은 2초 초반을 넘기지 않는다 — 연출이 새로운 루즈함이 되면 안 된다.
_TURN_CUE_DURATION_MS = 2200
_HIGHLIGHT_CUE_DURATION_MS = 3000
_GAME_FINISH_CUE_DURATION_MS = 4000


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
        return self._state_context_messages()

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
        current_player.scores[str(category)] = score
        scorer_name = current_player.playername
        score_label = _CATEGORY_TTS_LABELS.get(str(category), str(category))
        self.state.state_version += 1

        if self.state.is_final_round_complete:
            self.state.finish_game()
            self.state.state_version += 1
            self.state.last_message = (
                f"{scorer_name}님 {score_label} {score}점입니다. 게임이 종료되었습니다."
            )
            # Benchmark hook: 정상 게임 종료 (completion_rate 측정용).
            try:
                from benchmarks.common.trace_setup import bench_log
                import time as _t
                bench_log().info("game_end yacht normal %.6f", _t.time())
            except Exception:
                pass
            return [
                self._make_state_update(),
                self._make_score_cue(
                    cue="yacht_game_finish",
                    scorer=current_player,
                    category=str(category),
                    score_label=score_label,
                    score=score,
                    next_player=None,
                    duration_ms=_GAME_FINISH_CUE_DURATION_MS,
                ),
                self._emit_fusion_context(),
            ]

        self.state.advance_player()
        self.state.phase = YachtPhase.AWAITING_ROLL.value
        self.state.last_message = (
            f"{scorer_name}님 {score_label} {score}점입니다. "
            f"{self.state.current_player.playername}님 차례입니다."
        )
        is_highlight = str(category) in _HIGHLIGHT_CATEGORIES
        return [
            self._make_state_update(),
            self._make_score_cue(
                cue="yacht_turn_transition",
                scorer=current_player,
                category=str(category),
                score_label=score_label,
                score=score,
                next_player=self.state.current_player.playername,
                duration_ms=(
                    _HIGHLIGHT_CUE_DURATION_MS if is_highlight else _TURN_CUE_DURATION_MS
                ),
            ),
            self._emit_fusion_context(),
        ]

    def _make_score_cue(
        self,
        cue: str,
        scorer: Player,
        category: str,
        score_label: str,
        score: int,
        next_player: str | None,
        duration_ms: int,
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
                "category": category,
                "category_label": score_label,
                "score": score,
                "is_highlight": category in _HIGHLIGHT_CATEGORIES,
                "next_player": next_player,
                "duration_ms": duration_ms,
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
