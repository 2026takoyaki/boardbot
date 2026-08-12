"""템포 에이전트 — 턴 타이머 마일스톤에서 HIGH 우선순위 TTS 발화.

asyncio 백그라운드 태스크로 동작. 상태 전환 시 기존 태스크를 취소하고 새로 시작.
turn_timeout이 None이면 타이머를 만들지 않는다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable

from agents.context import AgentContext
from agents.tools import lines
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


class TempoAgent:
    """우선순위 2 (HIGH). 턴 타이머 경과를 음성으로 알린다."""

    name = "tempo"

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._tts_cb: TtsCb | None = None

    def set_tts_callback(self, cb: TtsCb) -> None:
        self._tts_cb = cb

    def on_state_change(self, ctx: AgentContext) -> None:
        """상태 전환 시 호출. 기존 타이머를 취소하고 새 타이머를 시작한다."""
        self._cancel()
        if ctx.turn_timeout is None or ctx.turn_timeout <= 0:
            return
        self._task = asyncio.create_task(
            self._run(ctx.turn_start_time, ctx.turn_timeout, ctx.phase_end_warning)
        )

    def stop(self) -> None:
        self._cancel()

    def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def _run(self, start_time: float, timeout: float, end_warning: str | None = None) -> None:
        if self._tts_cb is None:
            return
        if end_warning and timeout > 4:
            # 페이즈 종료 4초 전 경고 (야간 페이즈용). 비율 마일스톤 대신 사용.
            fire_at = start_time + timeout - 4
            wait = fire_at - time.time()
            if wait > 0:
                try:
                    await asyncio.sleep(wait)
                except asyncio.CancelledError:
                    return
            try:
                await self._tts_cb(end_warning, AudioPriority.HIGH)
            except Exception:
                logger.exception("[TempoAgent] TTS 발화 실패")
        else:
            for ratio, line_id in _MILESTONES:
                fire_at = start_time + timeout * ratio
                wait = fire_at - time.time()
                if wait > 0:
                    try:
                        await asyncio.sleep(wait)
                    except asyncio.CancelledError:
                        return
                text = lines.get(line_id)
                if not text:
                    continue
                try:
                    await self._tts_cb(text, AudioPriority.HIGH)
                except Exception:
                    logger.exception("[TempoAgent] TTS 발화 실패")
