"""에이전트 공통 컨텍스트 — 각 에이전트에 전달되는 게임 상태 스냅샷."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class AgentContext:
    game_type: str                          # "yacht" | "werewolf"
    fsm_state: str
    active_player: str | None
    players: list[dict[str, Any]]           # [{"player_id": ..., "playername": ...}]
    allowed_actors: list[str] = field(default_factory=list)
    expected_events: list[str] = field(default_factory=list)
    turn_start_time: float = field(default_factory=time.time)
    turn_timeout: float | None = None       # 초 단위. None이면 타이머 없음
    # 페이즈 종료 T-4초에 발화할 경고. 문장이 아니라 line_id다 — 세션이 문장을
    # 들고 있으면 그 한 줄에는 페르소나 말투가 닿지 않는다.
    phase_end_warning_line: str | None = None
    game_specific: dict[str, Any] = field(default_factory=dict)

    def player_name(self, player_id: str | None) -> str | None:
        if not player_id:
            return None
        return next(
            (p.get("playername") for p in self.players if p.get("player_id") == player_id),
            player_id,
        )
