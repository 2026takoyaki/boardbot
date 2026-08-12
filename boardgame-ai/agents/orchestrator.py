"""에이전트 오케스트레이터 — 우선순위 기반 에이전트 중재자.

우선순위 (낮을수록 높음):
  1. RulesAgent   (CRITICAL) — 규칙 위반 감지 시 즉시 개입, 하위 억제
  2. TempoAgent   (HIGH)     — 턴 타이머 마일스톤 알림 (백그라운드 태스크)
  3. ProgressAgent(NORMAL)   — 페이즈 전환 진행 내러티브
  4. StrategyAgent(LOW)      — 의사결정 시점 전략 추천 (활성화 시만)

사용:
    orchestrator = AgentOrchestrator(audio_manager)
    # 세션에서 FSM 상태 전환 시
    await orchestrator.on_state_change(ctx)
    # 세션에서 게임 이벤트 수신 시
    await orchestrator.on_game_event(event)
    # 전략 코칭 토글
    orchestrator.set_strategy_enabled(True)
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from core.audio import AudioPriority
from core.constants import AgentRole, MsgType
from core.envelope import WSMessage
from core.events import GameEvent

from agents.base import Intervention
from agents.context import AgentContext
from agents.progress_agent import ProgressAgent
from agents.rules_agent import RulesAgent
from agents.strategy_agent import StrategyAgent
from agents.tempo_agent import TempoAgent

if TYPE_CHECKING:
    from audio.manager import AudioManager

logger = logging.getLogger(__name__)

MessageCb = Callable[[WSMessage], Awaitable[None]]

_AGENT_ROLE_MAP: dict[str, str] = {
    "rules":    AgentRole.REFEREE.value,
    "tempo":    AgentRole.TEMPO.value,
    "progress": AgentRole.NARRATOR.value,
    "strategy": AgentRole.STRATEGY.value,
}


class AgentOrchestrator:
    def __init__(self, audio_manager: AudioManager) -> None:
        self._audio = audio_manager
        self._rules = RulesAgent()
        self._tempo = TempoAgent()
        self._progress = ProgressAgent()
        self._strategy = StrategyAgent()
        self._current_ctx: AgentContext | None = None
        self._state_version: int = 0
        self._broadcast: MessageCb | None = None
        self._tasks: set[asyncio.Task[None]] = set()

        self._tempo.set_tts_callback(
            lambda text, prio: self._send_tts(text, prio, AgentRole.TEMPO.value)
        )

    # ── 공개 인터페이스 ────────────────────────────────────────────────────────

    def set_broadcast(self, cb: MessageCb) -> None:
        """화면에도 띄워야 하는 개입(코치 등)을 내보낼 통로.

        오디오는 AudioManager가 알아서 가지만, 눈으로 보며 따라야 하는 조언은
        화면까지 가야 한다. 설정하지 않으면 발화만 하고 화면은 건드리지 않는다.
        """
        self._broadcast = cb

    def reset_for_new_game(self) -> None:
        """새 판 시작 시 호출 — 에이전트가 앞 판에 대해 기억하는 것을 비운다."""
        self._strategy.reset_coach()
        self._progress.reset()

    def set_strategy_enabled(self, enabled: bool) -> None:
        self._strategy.set_enabled(enabled)

    @property
    def strategy_enabled(self) -> bool:
        return self._strategy.enabled

    async def on_state_change(self, ctx: AgentContext, state_version: int = 0) -> None:
        """FSM 상태 전환 시 세션에서 호출."""
        self._current_ctx = ctx
        self._state_version = state_version

        # 1) 템포 타이머 재시작 (sync, 내부적으로 asyncio.create_task)
        self._tempo.on_state_change(ctx)

        # 2) 진행 에이전트 — 새 페이즈 안내
        result = self._progress.on_state_change(ctx)
        if result:
            await self._dispatch(result)
            if result.suppress_lower:
                return

        # 3) LLM을 쓰는 것들 — 백그라운드로 (지연이 있어도 게임 흐름 차단 없음).
        # 태스크 참조를 붙잡아 둔다 — 놓으면 GC가 실행 도중 회수할 수 있다.
        task = asyncio.create_task(self._run_llm_agents(ctx))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def on_game_event(self, event: GameEvent) -> None:
        """게임 이벤트 수신 시 세션에서 호출 (FSM 처리 이전에 호출 권장)."""
        if self._current_ctx is None:
            return
        result = self._rules.on_game_event(event, self._current_ctx)
        if not result:
            return
        # 제지가 먼저, 이유는 나중에. 설명을 기다렸다 함께 내보내면 이미 굴러간
        # 주사위 뒤에 제지가 도착한다.
        await self._dispatch(result)
        task = asyncio.create_task(self._run_rules_explain(result))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def stop(self) -> None:
        """세션 종료 시 호출 — 백그라운드 타이머·태스크 정리.

        정리하지 않으면 죽은 세션의 전략 태스크가 살아남아 이미 닫힌 소켓으로
        발화를 밀어 넣는다.
        """
        self._tempo.stop()
        for task in list(self._tasks):
            if not task.done():
                task.cancel()
        self._tasks.clear()

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    async def _run_rules_explain(self, violation: Intervention) -> None:
        detail = await self._rules.explain(violation)
        if detail:
            await self._dispatch(detail)

    async def _run_llm_agents(self, ctx: AgentContext) -> None:
        """생성이 필요한 개입들. 순서대로 — 동시에 부르면 두 멘트가 뒤엉킨다.

        상황 한마디가 먼저다. 방금 벌어진 일에 대한 반응이라 늦을수록 어색해지고,
        훈수는 어차피 다음 사람이 고민하는 동안 나오면 된다.
        """
        reaction = await self._progress.reaction(ctx)
        if reaction:
            await self._dispatch(reaction)

        result = await self._strategy.on_state_change_async(ctx)
        if result:
            await self._dispatch(result)

    async def _dispatch(self, intervention: Intervention) -> None:
        # 화면 먼저. 조언은 듣기 전에 눈에 들어와 있어야 따라갈 수 있고,
        # 합성 지연을 기다렸다 띄우면 말이 끝난 뒤에 글이 뜬다.
        if intervention.display:
            await self._send_agent_message(intervention)
        if intervention.tts_text:
            # delivery가 있으면 그 말투로. 목소리는 페르소나 것 그대로고
            # 톤만 갈린다(AudioManager가 agent 값으로 말투를 고른다).
            await self._send_tts(
                intervention.tts_text,
                intervention.priority,
                agent=intervention.delivery
                or _AGENT_ROLE_MAP.get(intervention.agent, AgentRole.NARRATOR.value),
                sequence_id=intervention.sequence_id,
                seq_index=intervention.seq_index,
            )

    async def _send_agent_message(self, intervention: Intervention) -> None:
        """화면에 띄울 에이전트 발언. text가 비면 화면에서 지우라는 뜻이다."""
        if self._broadcast is None:
            return
        msg = WSMessage(
            msg_type=MsgType.AGENT_MESSAGE.value,
            payload={
                "agent": intervention.agent,
                "text": intervention.tts_text or "",
                "transient": intervention.transient,
            },
            state_version=self._state_version,
        )
        try:
            await self._broadcast(msg)
        except Exception:
            logger.exception("[AgentOrchestrator] agent_message 전송 실패")

    async def _send_tts(
        self,
        text: str,
        priority: AudioPriority,
        agent: str = AgentRole.NARRATOR.value,
        sequence_id: str | None = None,
        seq_index: int = 0,
    ) -> None:
        try:
            await self._audio.enqueue_tts(
                text=text,
                agent=agent,
                priority=priority,
                sequence_id=sequence_id,
                seq_index=seq_index,
                state_version=self._state_version,
            )
        except Exception:
            logger.exception("[AgentOrchestrator] TTS 전송 실패 (agent=%s)", agent)
