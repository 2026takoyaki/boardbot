"""한밤의 늑대인간 게임 상태.

시스템은 각 플레이어가 어떤 역할 카드를 가졌는지 알지 못한다. 알고 있는 것은
이번 판에 사용하는 역할 덱(deck_roles)과 투표 결과뿐이며, 역할 배분·야간 행동
결과·승패 판정은 모두 플레이어들이 직접 카드를 공개해 처리한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from games.werewolf.ontology import WerewolfPhase

DEFAULT_DISCUSSION_SECONDS = 300


@dataclass
class WerewolfPlayerState:
    player_id: str
    voted_for: str | None = None  # 투표 대상 player_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "voted_for": self.voted_for,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WerewolfPlayerState:
        return cls(
            player_id=d["player_id"],
            voted_for=d.get("voted_for"),
        )


@dataclass
class WerewolfGameState:
    players: list[WerewolfPlayerState]
    player_order: list[str]            # player_id 순서
    deck_roles: list[str]              # 이번 판 역할 덱. 야간 페이즈 진행 여부를 정한다
    timer_remaining: int               # DAY_DISCUSSION 남은 시간(초)
    phase: str                         # WerewolfPhase value
    state_version: int = 0
    votes_locked: bool = False         # 카운트다운 종료 후 결과 확인 대기
    countdown_remaining: int | None = None  # 투표 카운트다운 남은 초 (None=비활성)
    executed: list[str] = field(default_factory=list)  # RESULT 진입 시 확정되는 최다 득표자

    @classmethod
    def new(
        cls,
        players: list[WerewolfPlayerState],
        deck_roles: list[str],
    ) -> WerewolfGameState:
        """플레이어와 역할 덱으로 초기 상태를 생성한다."""
        return cls(
            players=players,
            player_order=[p.player_id for p in players],
            deck_roles=list(deck_roles),
            timer_remaining=DEFAULT_DISCUSSION_SECONDS,
            phase=WerewolfPhase.NIGHT_START.value,
        )

    def get_player(self, player_id: str) -> WerewolfPlayerState:
        for p in self.players:
            if p.player_id == player_id:
                return p
        raise KeyError(f"Player not found: {player_id}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "players": [p.to_dict() for p in self.players],
            "player_order": list(self.player_order),
            "deck_roles": list(self.deck_roles),
            "timer_remaining": self.timer_remaining,
            "phase": self.phase,
            "state_version": self.state_version,
            "votes_locked": self.votes_locked,
            "countdown_remaining": self.countdown_remaining,
            "executed": list(self.executed),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WerewolfGameState:
        return cls(
            players=[WerewolfPlayerState.from_dict(p) for p in d["players"]],
            player_order=list(d["player_order"]),
            deck_roles=list(d.get("deck_roles", [])),
            timer_remaining=int(d["timer_remaining"]),
            phase=d["phase"],
            state_version=int(d.get("state_version", 0)),
            votes_locked=bool(d.get("votes_locked", False)),
            countdown_remaining=d.get("countdown_remaining"),
            executed=list(d.get("executed", [])),
        )
