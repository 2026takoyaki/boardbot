"""템포 에이전트 — 턴 타이머 마일스톤에서 HIGH 우선순위 TTS 발화.

asyncio 백그라운드 태스크로 동작. 상태 전환 시 기존 태스크를 취소하고 새로 시작.
turn_timeout이 None이면 타이머를 만들지 않는다.

LLM은 여기서 직접 부르지 않는다. 재촉은 제때 나와야 재촉이라 생성 지연을
감당할 수 없다 — 변형 문장은 게임 시작 전에 agents/tools/tempo_pool.py가
미리 만들어 두고, 이 에이전트는 그중 하나를 뽑아 쓰기만 한다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from agents.context import AgentContext
from agents.tools import lines, tempo_pool
from core.audio import AudioPriority

logger = logging.getLogger(__name__)

TtsCb = Callable[[str, AudioPriority], Awaitable[None]]

# (경과 비율, line_id) — 타임아웃의 해당 비율 시점에 발화.
# 멘트 원문은 agents/tools/lines.py가 소유한다 (페르소나 일괄 변환 대상).
_MILESTONES: list[tuple[float, str]] = [
    (0.5,  "tempo.half"),
    (0.8,  "tempo.hurry"),
    (0.95, "tempo.almost"),
]

# 야간 마감 지시("눈을 다시 감아주세요")를 시작할 시점 — 단계 종료 몇 초 전인가.
#
# 이 시간 안에 두 가지가 들어가야 한다: 지시를 끝까지 읽는 시간과, 듣고 실제로
# 눈을 감을 시간. 지시는 16자 이내로 묶여 있으므로(tempo_pool의 _MAX_LEN_BY_LINE)
# 읽는 데 3초 남짓, 나머지 2초가 눈을 감는 시간이다.
#
# 야간 단계 길이(games/werewolf/fsm.py)는 이 값을 빼고 나서 안내와 조언이
# 들어갈 수 있게 잡혀 있다. 여기를 늘리면 그쪽도 같이 늘려야 한다 —
# tests/test_werewolf_fsm.py 가 그 관계를 검사한다.
PHASE_END_WARNING_LEAD = 5.0


class TempoAgent:
    """우선순위 2 (HIGH). 턴 타이머 경과를 음성으로 알린다."""

    name = "tempo"

    def __init__(self) -> None:
        self._task: asyncio.Task[None] | None = None
        self._tts_cb: TtsCb | None = None

    def set_tts_callback(self, cb: TtsCb) -> None:
        self._tts_cb = cb

    def on_state_change(self, ctx: AgentContext) -> None:
        """상태 전환 시 호출. 기존 타이머를 취소하고 새 타이머를 시작한다."""
        self._cancel()
        if ctx.turn_timeout is None or ctx.turn_timeout <= 0:
            return
        self._task = asyncio.create_task(
            self._run(ctx.turn_start_time, ctx.turn_timeout, ctx.phase_end_warning_line)
        )

    def stop(self) -> None:
        self._cancel()

    def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _run(
        self, start_time: float, timeout: float, end_warning_line: str | None = None
    ) -> None:
        if self._tts_cb is None:
            return
        if end_warning_line and timeout > PHASE_END_WARNING_LEAD:
            # 페이즈 종료 직전 마감 지시 (야간 페이즈용). 비율 마일스톤 대신 사용.
            fire_at = start_time + timeout - PHASE_END_WARNING_LEAD
            wait = fire_at - time.time()
            if wait > 0:
                try:
                    await asyncio.sleep(wait)
                except asyncio.CancelledError:
                    return
            # 이 한 줄은 재촉이 아니라 **진행에 필요한 지시**다. 밀리면 다음
            # 단계가 시작되며 통째로 버려지고, 그러면 눈을 감으라는 말을 아무도
            # 못 듣는다(실제로 전략 조언이 재생 중이면 항상 그렇게 됐다).
            # 그래서 재생 중인 것을 끊고 나간다.
            await self._say(end_warning_line, preempt=True)
        else:
            for ratio, line_id in _MILESTONES:
                fire_at = start_time + timeout * ratio
                wait = fire_at - time.time()
                if wait > 0:
                    try:
                        await asyncio.sleep(wait)
                    except asyncio.CancelledError:
                        return
                await self._say(line_id)

    async def _say(self, line_id: str, preempt: bool = False) -> None:
        """미리 만들어 둔 변형 중 하나로 말한다. 없으면 고정 멘트 그대로.

        preempt=True면 재생 중인 발화를 끊고 나간다. 비율 마일스톤("절반이
        지났습니다")은 놓쳐도 그만이라 기다리지만, 야간 마감 지시는 그 단계가
        끝나기 전에 반드시 들려야 해서 기다릴 수 없다.
        """
        text = tempo_pool.pick(line_id) or lines.get(line_id)
        if not text or self._tts_cb is None:
            return
        priority = AudioPriority.CRITICAL if preempt else AudioPriority.HIGH
        try:
            await self._tts_cb(text, priority)
        except Exception:
            logger.exception("[TempoAgent] TTS 발화 실패")
