"""규칙 에이전트 — 차례 위반·허용되지 않는 행동 감지 시 CRITICAL TTS 발화.

2단 발화를 한다.

    1단  즉답    캐시된 고정 멘트("지금은 성민님 차례입니다.")를 0지연으로
    2단  설명    LLM이 만든 한 문장을 같은 sequence_id로 뒤에 붙여

제지는 늦으면 의미가 없다. 이미 주사위를 굴려버린 뒤에 "지금은 당신 차례가
아닙니다"라고 해봐야 판이 어그러진 다음이다. 그래서 1단은 절대 생성하지
않는다. 반대로 "왜"는 조금 늦어도 되므로 그 자리를 LLM이 맡는다.

두 발화는 sequence_id로 묶여 순서가 보장된다. 안 묶으면 설명이 즉답을
앞지르거나 덮어써서, 정작 급한 제지가 안 들린다.
"""

from __future__ import annotations

import logging
import time
import uuid

from agents.base import BaseAgent, Intervention
from agents.context import AgentContext
from agents.tools import lines, llm
from core.audio import AudioPriority
from core.events import GameEvent

logger = logging.getLogger(__name__)

# 설명은 한 문장이다. 제지당한 사람을 붙잡고 길게 설명하면 그게 더 벌이다.
_EXPLAIN_MAX_TOKENS = 80

# 설명이 이보다 늦으면 포기한다. 즉답은 이미 나갔으니 없어도 진행은 된다.
_EXPLAIN_TIMEOUT = 3.0

# 같은 위반을 이 시간 안에 다시 보면 넘어간다.
#
# 카메라는 한 번의 행동을 여러 프레임에서 잡는다. 손이 트레이 위에 머무는
# 동안 같은 위반이 연달아 올라오면, 진행자가 같은 말을 다섯 번 외치고
# (CRITICAL이라 서로를 끊는다) 그때마다 LLM도 한 번씩 불린다.
# 두 번째부터는 사람에게도 소음이고 비용도 그만큼 나간다.
#
# 즉답 자체를 막는다. 설명만 막으면 정작 시끄러운 쪽이 그대로 남는다.
_VIOLATION_COOLDOWN = 5.0

# 설명을 기다리는 위반의 상한. 세션이 끝나 설명 태스크가 취소되면 항목이
# 남는데, 지워줄 사람이 없어 프로세스가 사는 동안 쌓인다.
_MAX_PENDING = 8


class RulesAgent(BaseAgent):
    """우선순위 1 (CRITICAL). 규칙 위반이 감지되면 즉시 개입하고 하위 에이전트를 억제."""

    name = "rules"

    def __init__(self) -> None:
        # sequence_id → 위반 상황. 즉답을 만든 곳과 설명을 만드는 곳이 다른
        # 시점이라(설명은 백그라운드), 무엇 때문에 제지했는지를 넘겨줄 자리가
        # 필요하다. 설명을 만들 때 꺼내 쓰고 지운다.
        self._pending_situation: dict[str, str] = {}
        self._last_key: str = ""
        self._last_at: float = 0.0

    def reset(self) -> None:
        """새 판 시작 시. 앞 판의 위반을 기억하고 있을 이유가 없다."""
        self._pending_situation.clear()
        self._last_key = ""
        self._last_at = 0.0

    def on_game_event(self, event: GameEvent, ctx: AgentContext) -> Intervention | None:
        actor = event.actor_id

        # actor가 없거나 제한 목록 자체가 없으면 규칙 검사 불필요
        if not actor or not ctx.allowed_actors:
            return None

        # 허용되지 않은 액터 감지
        if actor not in ctx.allowed_actors:
            active_name = ctx.player_name(ctx.active_player)
            msg = (
                lines.render("rules.wrong_turn", player=active_name)
                if active_name
                else lines.get("rules.wrong_turn_unknown")
            )
            return self._violation(
                msg, "차례가 아닌 사람이 행동했습니다.", key=f"wrong_turn:{actor}"
            )

        # 허용되지 않은 이벤트 타입 감지
        if ctx.expected_events and event.event_type not in ctx.expected_events:
            return self._violation(
                lines.get("rules.invalid_action"),
                "지금 페이즈에서 할 수 없는 행동을 했습니다.",
                key=f"invalid_action:{actor}:{event.event_type}",
            )

        return None

    def _is_repeat(self, key: str) -> bool:
        """방금 제지한 그 위반인가. 카메라가 한 행동을 여러 번 잡은 경우다."""
        now = time.monotonic()
        if key == self._last_key and now - self._last_at < _VIOLATION_COOLDOWN:
            return True
        self._last_key = key
        self._last_at = now
        return False

    def _violation(self, text: str | None, situation: str, key: str) -> Intervention | None:
        """즉답 개입. 뒤에 붙일 설명을 위해 시퀀스를 열어 둔다."""
        if self._is_repeat(key):
            return None
        intervention = Intervention(
            agent=self.name,
            tts_text=text,
            priority=AudioPriority.CRITICAL,
            suppress_lower=True,
            sequence_id=f"rules-{uuid.uuid4().hex[:8]}",
            seq_index=0,
        )
        # 설명 태스크가 취소되면(세션 종료 등) 항목이 남고 지워줄 사람이 없다.
        # 오래된 것부터 버려 상한을 지킨다 — 어차피 그 위반은 이미 지나갔다.
        while len(self._pending_situation) >= _MAX_PENDING:
            # dict는 삽입 순서를 지키므로 첫 키가 가장 오래된 것이다.
            # popitem()은 반대쪽(최신)을 빼므로 여기서는 쓸 수 없다.
            dropped = next(iter(self._pending_situation))
            del self._pending_situation[dropped]
            logger.debug("[RulesAgent] 설명을 못 받은 위반을 버림 (%s)", dropped)
        self._pending_situation[intervention.sequence_id or ""] = situation
        return intervention

    # ── 2단: 설명 (LLM, 즉답 뒤에 붙는다) ──────────────────────────────────────

    async def explain(self, intervention: Intervention) -> Intervention | None:
        """즉답에 이어 붙일 한 문장. 못 만들면 붙이지 않는다."""
        sequence_id = intervention.sequence_id
        situation = self._pending_situation.pop(sequence_id or "", None)
        if not sequence_id or not situation:
            return None

        result = await llm.get_client().complete(
            llm.persona_style()
            + "당신은 보드게임 진행자입니다. 방금 제지한 이유를 한 문장으로 "
            "짧게 덧붙이세요. 제지 자체는 이미 했으니 반복하지 마세요. "
            "이름이나 숫자를 새로 만들지 마세요.",
            situation,
            max_tokens=_EXPLAIN_MAX_TOKENS,
            timeout=_EXPLAIN_TIMEOUT,
            tag="rules.explain",
        )
        if not result.text:
            return None
        return Intervention(
            agent=self.name,
            tts_text=result.text,
            # 설명은 CRITICAL이 아니다. 급한 것은 제지였고 그건 이미 나갔다.
            # CRITICAL로 두면 뒤이어 오는 다른 발화를 이유 없이 끊는다.
            priority=AudioPriority.HIGH,
            suppress_lower=False,
            sequence_id=sequence_id,
            seq_index=1,
        )
