"""요트다이스 FSM 상태 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from core.models import Player
from games.yacht.scoring import ALL_CATEGORIES, total_score, upper_subtotal


class YachtPhase(StrEnum):
    AWAITING_ROLL = "AWAITING_ROLL"
    AWAITING_KEEP = "AWAITING_KEEP"
    AWAITING_SCORE = "AWAITING_SCORE"
    GAME_END = "GAME_END"


class YachtEventType(StrEnum):
    ROLL_CONFIRMED = "ROLL_CONFIRMED"
    ROLL_UNREADABLE = "ROLL_UNREADABLE"
    DICE_ESCAPED = "DICE_ESCAPED"
    RULE_VIOLATION = "RULE_VIOLATION"
    RULE_VIOLATION_LOWER = "rule_violation"


class YachtInputType(StrEnum):
    DICE_REROLL_REQUESTED = "DICE_REROLL_REQUESTED"
    DICE_KEEP_SELECTED = "DICE_KEEP_SELECTED"
    SCORE_CATEGORY_SELECTED = "SCORE_CATEGORY_SELECTED"
    RESOLVE_UNREADABLE_ROLL = "RESOLVE_UNREADABLE_ROLL"


@dataclass
class YachtPlayerState:
    player_id: str
    playername: str
    scores: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return total_score(self.scores)

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "playername": self.playername,
            "scores": dict(self.scores),
            "upper_subtotal": upper_subtotal(self.scores),
            "total": self.total,
        }


@dataclass
class YachtGameState:
    players: list[YachtPlayerState]
    current_player_index: int = 0
    phase: str = YachtPhase.AWAITING_ROLL.value
    roll_count: int = 0
    dice_values: list[int | None] = field(default_factory=list)
    keep_mask: list[bool] = field(default_factory=lambda: [False] * 5)
    state_version: int = 0
    winner: str | None = None
    unreadable_roll: dict[str, Any] | None = None
    last_message: str | None = None

    @classmethod
    def new(cls, players: list[Player | str | dict[str, Any]]) -> YachtGameState:
        if not players:
            raise ValueError("요트다이스는 최소 1명의 플레이어가 필요합니다.")

        player_states: list[YachtPlayerState] = []
        for index, player in enumerate(players, start=1):
            if isinstance(player, Player):
                player_states.append(YachtPlayerState(player.player_id, player.playername))
            elif isinstance(player, str):
                player_states.append(YachtPlayerState(player, player))
            else:
                player_id = str(player.get("player_id", f"p_{index}"))
                name = str(player.get("playername", player.get("name", player_id)))
                player_states.append(YachtPlayerState(player_id, name))

        return cls(players=player_states)

    @property
    def current_player(self) -> YachtPlayerState:
        return self.players[self.current_player_index]

    @property
    def player_order(self) -> list[str]:
        return [p.player_id for p in self.players]

    @property
    def available_categories(self) -> list[str]:
        used = self.current_player.scores
        return [cat.value for cat in ALL_CATEGORIES if cat.value not in used]

    @property
    def is_final_round_complete(self) -> bool:
        return all(len(p.scores) == len(ALL_CATEGORIES) for p in self.players)

    def has_open_category(self, player: YachtPlayerState) -> bool:
        return len(player.scores) < len(ALL_CATEGORIES)

    def advance_player(self) -> None:
        """다음 차례로 넘긴다. 점수판을 다 채운 사람은 건너뛴다.

        건너뛰지 않으면 고를 칸이 하나도 없는 사람에게 차례가 가서 게임이 멈춘다.
        종료 조건은 "전원이 다 채웠는가"라 그 상태로는 끝나지도 않는다.

        정상 플레이에서는 모두가 매 턴 한 칸씩 채우므로 칸 수가 어긋날 일이
        없지만, 되돌리기나 상태 복원처럼 턴 수가 어긋나는 경로가 있으면 그대로
        데드락이 된다. 한 사람이라도 남아 있으면 그 사람에게 차례가 가야 한다.
        """
        total = len(self.players)
        for step in range(1, total + 1):
            candidate = (self.current_player_index + step) % total
            if self.has_open_category(self.players[candidate]):
                self.current_player_index = candidate
                break
        else:
            # 전원이 다 채웠다. 종료 판정이 곧바로 뒤따르므로 자리만 넘긴다.
            self.current_player_index = (self.current_player_index + 1) % total

        self.roll_count = 0
        self.dice_values = []
        self.keep_mask = [False] * 5
        self.unreadable_roll = None

    def finish_game(self) -> None:
        self.phase = YachtPhase.GAME_END.value
        best_total = max(p.total for p in self.players)
        winners = [p.player_id for p in self.players if p.total == best_total]
        self.winner = winners[0] if len(winners) == 1 else ",".join(winners)

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_type": "yacht",
            "phase": self.phase,
            "state_version": self.state_version,
            "players": [p.to_dict() for p in self.players],
            "player_order": self.player_order,
            "current_player_id": self.current_player.player_id,
            "current_player_index": self.current_player_index,
            "roll_count": self.roll_count,
            "remaining_rolls": max(0, 3 - self.roll_count),
            "dice_values": list(self.dice_values),
            "keep_mask": list(self.keep_mask),
            "available_categories": self.available_categories,
            "winner": self.winner,
            "unreadable_roll": self.unreadable_roll,
            "last_message": self.last_message,
        }
