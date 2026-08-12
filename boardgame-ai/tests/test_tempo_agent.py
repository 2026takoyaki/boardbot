"""TempoAgent가 실제로 무엇을 말하는가.

세션이 넘기는 것은 문장이 아니라 line_id다. 이 경계가 무너지면 그 한 줄만
표준어로 나가는데(실제로 werewolf_session이 "눈을 다시 감아주세요."를 직접
들고 있었다), 소리로만 드러나서 테스트 없이는 알아채기 어렵다.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from agents.context import AgentContext
from agents.tempo_agent import TempoAgent
from agents.tools import lines, tempo_pool
from core.audio import AudioPriority


@pytest.fixture(autouse=True)
def _clean():
    yield
    tempo_pool.clear()


def _ctx(**kw: object) -> AgentContext:
    base = {
        "game_type": "werewolf",
        "fsm_state": "NIGHT_SEER",
        "active_player": None,
        "players": [],
        "turn_start_time": time.time(),
    }
    base.update(kw)
    return AgentContext(**base)  # type: ignore[arg-type]


async def _collect(agent: TempoAgent) -> list[tuple[str, AudioPriority]]:
    said: list[tuple[str, AudioPriority]] = []

    async def cb(text: str, priority: AudioPriority) -> None:
        said.append((text, priority))

    agent.set_tts_callback(cb)
    return said


@pytest.mark.anyio
async def test_페이즈_종료_경고를_line_id로_받아_문장으로_바꾼다():
    agent = TempoAgent()
    said = await _collect(agent)

    # timeout 4.05 → 경고 시점이 거의 지금. 4보다 커야 경고 경로를 탄다.
    agent.on_state_change(
        _ctx(turn_timeout=4.05, phase_end_warning_line="tempo.close_eyes_again")
    )
    await asyncio.sleep(0.2)

    assert said == [(lines.get("tempo.close_eyes_again"), AudioPriority.HIGH)]


@pytest.mark.anyio
async def test_풀에_변형이_있으면_그중_하나로_말한다():
    tempo_pool._pool["tempo.close_eyes_again"] = ["눈 다시 감으셔유~"]
    agent = TempoAgent()
    said = await _collect(agent)

    agent.on_state_change(
        _ctx(turn_timeout=4.05, phase_end_warning_line="tempo.close_eyes_again")
    )
    await asyncio.sleep(0.2)

    assert said == [("눈 다시 감으셔유~", AudioPriority.HIGH)]


@pytest.mark.anyio
async def test_타임아웃이_없으면_아무_말도_하지_않는다():
    agent = TempoAgent()
    said = await _collect(agent)

    agent.on_state_change(_ctx(turn_timeout=None))
    await asyncio.sleep(0.1)

    assert said == []


@pytest.mark.anyio
async def test_상태가_바뀌면_앞_페이즈의_재촉은_취소된다():
    agent = TempoAgent()
    said = await _collect(agent)

    agent.on_state_change(
        _ctx(turn_timeout=4.2, phase_end_warning_line="tempo.close_eyes_again")
    )
    agent.on_state_change(_ctx(turn_timeout=None))  # 다음 페이즈로 넘어감
    await asyncio.sleep(0.4)

    assert said == []
