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
from agents.tempo_agent import PHASE_END_WARNING_LEAD, TempoAgent
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

    # 리드보다 아주 조금 길게 → 마감 지시가 거의 즉시 나간다. 리드보다
    # 짧으면 비율 마일스톤 경로로 새므로 상수에서 뽑아 쓴다.
    agent.on_state_change(
        _ctx(
            turn_timeout=PHASE_END_WARNING_LEAD + 0.05,
            phase_end_warning_line="tempo.close_eyes_again",
        )
    )
    await asyncio.sleep(0.2)

    assert said == [(lines.get("tempo.close_eyes_again"), AudioPriority.CRITICAL)]


@pytest.mark.anyio
async def test_야간_마감_지시는_재생_중인_말을_끊고_나간다():
    """ "눈을 다시 감아주세요"는 재촉이 아니라 진행에 필요한 지시다.

    HIGH로 두면 재생 중인 발화를 못 끊고 뒤에서 기다리는데, 야간 단계는 4초 뒤에
    끝나버리므로 그대로 다음 단계 안내에 밀려 통째로 버려진다. 전략 조언이
    재생 중이면 항상 그렇게 됐다 — 그래서 끊고 나가야 한다.
    """
    agent = TempoAgent()
    said = await _collect(agent)

    agent.on_state_change(
        _ctx(
            turn_timeout=PHASE_END_WARNING_LEAD + 0.05,
            phase_end_warning_line="tempo.close_eyes_again",
        )
    )
    await asyncio.sleep(0.2)

    assert said and said[0][1] == AudioPriority.CRITICAL


@pytest.mark.anyio
async def test_비율_마일스톤은_끊지_않는다():
    """ "절반이 지났습니다"는 놓쳐도 그만이다. 말하던 것을 끊을 이유가 없다."""
    agent = TempoAgent()
    said = await _collect(agent)

    # phase_end_warning_line 없이 → 비율 마일스톤 경로.
    agent.on_state_change(_ctx(turn_timeout=0.2))
    await asyncio.sleep(0.5)

    assert said, "마일스톤이 하나도 안 나왔다"
    assert all(priority == AudioPriority.HIGH for _text, priority in said)


@pytest.mark.anyio
async def test_풀에_변형이_있으면_그중_하나로_말한다():
    tempo_pool._pool["tempo.close_eyes_again"] = ["눈 다시 감으셔유~"]
    agent = TempoAgent()
    said = await _collect(agent)

    agent.on_state_change(
        _ctx(
            turn_timeout=PHASE_END_WARNING_LEAD + 0.05,
            phase_end_warning_line="tempo.close_eyes_again",
        )
    )
    await asyncio.sleep(0.2)

    assert said == [("눈 다시 감으셔유~", AudioPriority.CRITICAL)]


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
        _ctx(
            turn_timeout=PHASE_END_WARNING_LEAD + 0.2,
            phase_end_warning_line="tempo.close_eyes_again",
        )
    )
    agent.on_state_change(_ctx(turn_timeout=None))  # 다음 페이즈로 넘어감
    await asyncio.sleep(0.4)

    assert said == []
