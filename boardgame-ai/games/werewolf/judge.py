"""한밤의 늑대인간 투표 집계.

시스템은 플레이어의 역할을 알지 못하므로 승패를 판정하지 않는다. 누가 몇 표를
받았고 누가 처형됐는지까지만 계산하고, 그 뒤의 카드 공개와 승패 판단은
플레이어들이 직접 한다.
"""

from __future__ import annotations

from games.werewolf.state import WerewolfGameState


def tally_votes(state: WerewolfGameState) -> dict[str, int]:
    """각 플레이어의 득표 수를 반환한다."""
    counts: dict[str, int] = {}
    for p in state.players:
        if p.voted_for:
            counts[p.voted_for] = counts.get(p.voted_for, 0) + 1
    return counts


def find_executed(state: WerewolfGameState) -> list[str]:
    """가장 많이 득표한 플레이어를 반환한다.

    동률이면 모두 포함. 3인 이상에서 전원이 1표씩 분산되면 아무도 처형 안 됨.
    """
    counts = tally_votes(state)
    if not counts:
        return []
    max_votes = max(counts.values())
    # 3인 이상에서 최대 득표가 1표 = 전원 분산 → 처형 없음
    if max_votes == 1 and len(state.players) >= 3:
        return []
    return [pid for pid, cnt in counts.items() if cnt == max_votes]
