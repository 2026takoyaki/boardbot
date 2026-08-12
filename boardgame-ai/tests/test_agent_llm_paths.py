"""네 에이전트가 LLM을 각자의 방식으로 부른다.

같은 LLM이라도 누가 기다리느냐에 따라 부르는 법이 달라야 한다. 여기서
지키는 것은 그 차이다.

    Rules     즉답이 먼저 나가고 설명이 뒤에 붙는다 (순서 보장)
    Progress  안내는 LLM 없이 즉시, 한마디만 나중에
    Tempo     발화 시점에 LLM을 부르지 않는다 (test_tempo_pool.py)
    Strategy  그 자리에서 불러도 된다 (test_llm.py)

실제 API를 부르지 않는다.
"""

from __future__ import annotations

import pytest

from agents.base import Intervention
from agents.context import AgentContext
from agents.progress_agent import ProgressAgent
from agents.rules_agent import RulesAgent
from agents.tools import llm
from agents.tools.llm import LLMClient, LLMResult
from core.audio import AudioPriority
from core.events import GameEvent


class _StubClient(LLMClient):
    def __init__(self, text: str | None) -> None:
        super().__init__()
        self.prompts: list[tuple[str, str]] = []
        self._text = text

    async def complete(self, system: str, user: str, **kwargs: object) -> LLMResult:
        self.prompts.append((system, user))
        return LLMResult(
            text=self._text,
            ok=self._text is not None,
            latency_ms=1.0,
            error=None if self._text else "테스트 실패",
        )


@pytest.fixture(autouse=True)
def _clean():
    yield
    llm.set_client(None)


def _yacht_ctx(line_id: str, **params: object) -> AgentContext:
    return AgentContext(
        game_type="yacht",
        fsm_state="AWAITING_ROLL",
        active_player=None,
        players=[],
        game_specific={"narration": {"line_id": line_id, "params": params}},
    )


# ── ProgressAgent: 안내는 즉시, 한마디는 나중에 ────────────────────────────────


def test_안내는_llm_없이_나간다():
    """LLM이 아예 없어도 진행 안내는 나가야 한다 — 여기서 막히면 게임이 멈춘다."""
    llm.set_client(_StubClient(None))
    agent = ProgressAgent()

    result = agent.on_state_change(
        _yacht_ctx("yacht.score_recorded", scorer="성민", label="풀하우스", score=25, next="지훈")
    )

    assert result is not None
    assert result.tts_text
    assert llm.get_client().stats()["calls"] == 0  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_큰_점수에는_한마디_덧붙인다():
    llm.set_client(_StubClient("오, 풀하우스 나왔네유!"))
    agent = ProgressAgent()

    result = await agent.reaction(
        _yacht_ctx("yacht.score_recorded", scorer="성민", label="풀하우스", score=25)
    )

    assert result is not None
    assert result.tts_text == "오, 풀하우스 나왔네유!"
    assert result.priority == AudioPriority.NORMAL


@pytest.mark.anyio
async def test_작은_점수에는_침묵한다():
    """4점짜리마다 감탄하면 요트가 터졌을 때 올릴 톤이 남지 않는다."""
    stub = _StubClient("굳이 할 말")
    llm.set_client(stub)
    agent = ProgressAgent()

    result = await agent.reaction(
        _yacht_ctx("yacht.score_recorded", scorer="성민", label="1점짜리", score=4)
    )

    assert result is None
    assert stub.prompts == []  # 부르지도 않는다


@pytest.mark.anyio
async def test_게임_종료는_점수가_낮아도_반응한다():
    llm.set_client(_StubClient("끝났슈."))
    agent = ProgressAgent()

    result = await agent.reaction(
        _yacht_ctx("yacht.game_finish", scorer="성민", label="1점짜리", score=3)
    )

    assert result is not None


@pytest.mark.anyio
async def test_같은_순간에_두_번_반응하지_않는다():
    llm.set_client(_StubClient("한마디"))
    agent = ProgressAgent()
    ctx = _yacht_ctx("yacht.score_recorded", scorer="성민", label="풀하우스", score=25)

    assert await agent.reaction(ctx) is not None
    assert await agent.reaction(ctx) is None  # 같은 상태가 다시 통지돼도


@pytest.mark.anyio
async def test_llm이_실패하면_한마디는_그냥_빠진다():
    """안내는 이미 나갔으므로 침묵이 생기지 않는다."""
    llm.set_client(_StubClient(None))
    agent = ProgressAgent()

    result = await agent.reaction(
        _yacht_ctx("yacht.score_recorded", scorer="성민", label="요트", score=50)
    )

    assert result is None


# ── RulesAgent: 2단 발화 ───────────────────────────────────────────────────────


def _violation_ctx() -> AgentContext:
    return AgentContext(
        game_type="yacht",
        fsm_state="AWAITING_ROLL",
        active_player="p1",
        players=[{"player_id": "p1", "playername": "성민"}],
        allowed_actors=["p1"],
    )


def _foul() -> GameEvent:
    return GameEvent(
        event_type="dice_rolled", actor_id="p2", confidence=1.0, frame_id=0
    )


def test_제지는_llm_없이_즉시_나간다():
    llm.set_client(_StubClient(None))
    agent = RulesAgent()

    result = agent.on_game_event(_foul(), _violation_ctx())

    assert result is not None
    assert "성민" in (result.tts_text or "")
    assert result.priority == AudioPriority.CRITICAL
    # 뒤에 설명을 붙일 수 있도록 시퀀스가 열려 있어야 한다.
    assert result.sequence_id
    assert result.seq_index == 0
    assert llm.get_client().stats()["calls"] == 0  # type: ignore[union-attr]


@pytest.mark.anyio
async def test_설명이_제지_뒤에_같은_시퀀스로_붙는다():
    llm.set_client(_StubClient("아직 성민님 차례가 안 끝났슈."))
    agent = RulesAgent()

    violation = agent.on_game_event(_foul(), _violation_ctx())
    assert violation is not None
    detail = await agent.explain(violation)

    assert detail is not None
    assert detail.sequence_id == violation.sequence_id
    assert detail.seq_index == 1
    # 급한 것은 제지였고 그건 이미 나갔다. 설명이 남의 발화를 끊으면 안 된다.
    assert detail.priority == AudioPriority.HIGH
    assert detail.suppress_lower is False


@pytest.mark.anyio
async def test_설명은_같은_제지에_두_번_붙지_않는다():
    llm.set_client(_StubClient("설명"))
    agent = RulesAgent()

    violation = agent.on_game_event(_foul(), _violation_ctx())
    assert violation is not None
    assert await agent.explain(violation) is not None
    assert await agent.explain(violation) is None


@pytest.mark.anyio
async def test_llm이_실패해도_제지는_이미_나갔다():
    llm.set_client(_StubClient(None))
    agent = RulesAgent()

    violation = agent.on_game_event(_foul(), _violation_ctx())
    assert violation is not None and violation.tts_text  # 제지는 멀쩡하다
    assert await agent.explain(violation) is None  # 설명만 빠진다


@pytest.mark.anyio
async def test_시퀀스가_없는_개입에는_설명을_붙이지_않는다():
    llm.set_client(_StubClient("설명"))
    agent = RulesAgent()

    stray = Intervention(
        agent="rules", tts_text="어디서 온지 모를 개입", priority=AudioPriority.CRITICAL
    )

    assert await agent.explain(stray) is None
