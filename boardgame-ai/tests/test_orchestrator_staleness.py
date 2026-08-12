"""늦게 도착한 LLM 발화가 "지금 것"으로 둔갑하지 않는다.

LLM은 2~4초 뒤에 돌아온다. 그 사이 판은 넘어가 있다. 발화를 내보낼 때
그 시점의 state_version을 읽으면, 지나간 상황에 대한 말이 최신으로 찍혀
AudioManager의 stale 폐기를 그대로 통과한다.

둘을 다르게 다룬다.
    훈수    "여기에 넣으세요"는 그 결정을 앞둔 사람에게만 맞는 말이다 → 버린다
    한마디  "풀하우스 나왔네"는 이미 벌어진 일이라 늦어도 맞는 말이다 → 내보낸다
"""

from __future__ import annotations

import asyncio

import pytest

from agents.base import Intervention
from agents.context import AgentContext
from agents.orchestrator import AgentOrchestrator
from core.audio import AudioPriority


class _FakeAudio:
    """AudioManager 중 오케스트레이터가 쓰는 표면만."""

    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def enqueue_tts(self, **kwargs: object) -> str:
        self.sent.append(kwargs)
        return "pb"


def _ctx(**kw: object) -> AgentContext:
    base = {
        "game_type": "yacht",
        "fsm_state": "AWAITING_SCORE",
        "active_player": None,
        "players": [],
    }
    base.update(kw)
    return AgentContext(**base)  # type: ignore[arg-type]


def _tip(text: str) -> Intervention:
    return Intervention(agent="strategy", tts_text=text, priority=AudioPriority.LOW)


def _make() -> tuple[AgentOrchestrator, _FakeAudio]:
    audio = _FakeAudio()
    return AgentOrchestrator(audio), audio  # type: ignore[arg-type]


@pytest.mark.anyio
async def test_늦게_온_훈수는_판이_넘어갔으면_버린다():
    orch, audio = _make()

    async def slow_advice(ctx: AgentContext) -> Intervention:
        await asyncio.sleep(0.05)
        return _tip("이 눈이면 풀하우스에 넣으세요.")

    orch._strategy.on_state_change_async = slow_advice  # type: ignore[assignment]

    await orch.on_state_change(_ctx(), state_version=5)
    orch._state_version = 6  # 그 사이 사람이 점수를 넣어버렸다
    await asyncio.sleep(0.2)

    assert audio.sent == []


@pytest.mark.anyio
async def test_판이_그대로면_훈수가_나간다():
    orch, audio = _make()

    async def advice(ctx: AgentContext) -> Intervention:
        return _tip("이 눈이면 풀하우스에 넣으세요.")

    orch._strategy.on_state_change_async = advice  # type: ignore[assignment]

    await orch.on_state_change(_ctx(), state_version=5)
    await asyncio.sleep(0.1)

    assert len(audio.sent) == 1
    # 만들어진 당시 버전으로 찍혀야 한다. 지금 값을 읽으면 옛말이 최신이 된다.
    assert audio.sent[0]["state_version"] == 5


@pytest.mark.anyio
async def test_늦게_온_한마디는_판이_넘어가도_내보낸다():
    """이미 벌어진 일에 대한 말이라 늦었다고 틀린 말이 되지 않는다."""
    orch, audio = _make()

    async def slow_reaction(ctx: AgentContext) -> Intervention:
        await asyncio.sleep(0.05)
        return Intervention(
            agent="progress", tts_text="오, 풀하우스!", priority=AudioPriority.NORMAL
        )

    orch._progress.reaction = slow_reaction  # type: ignore[assignment]

    await orch.on_state_change(_ctx(), state_version=5)
    orch._state_version = 6
    await asyncio.sleep(0.2)

    assert [s["text"] for s in audio.sent] == ["오, 풀하우스!"]
    # 내보내되 옛 상황의 말이라는 표시는 남긴다.
    assert audio.sent[0]["state_version"] == 5


@pytest.mark.anyio
async def test_state_version을_안_쓰는_게임에서는_버리지_않는다():
    """0으로 고정된 게임에서는 판단할 근거가 없다. 그럴 땐 말하는 쪽을 택한다."""
    orch, audio = _make()

    async def slow_advice(ctx: AgentContext) -> Intervention:
        await asyncio.sleep(0.05)
        return _tip("훈수")

    orch._strategy.on_state_change_async = slow_advice  # type: ignore[assignment]

    await orch.on_state_change(_ctx(), state_version=0)
    await asyncio.sleep(0.2)

    assert len(audio.sent) == 1
