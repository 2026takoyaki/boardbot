"""네 에이전트가 한 오디오 큐 위에서 함께 도는 흐름.

각 에이전트는 따로 테스트되지만, 실제로 문제가 나는 곳은 넷이 겹칠 때다.
가짜 AudioManager가 아니라 진짜를 쓴다 — 우선순위 정렬·CRITICAL 인터럽트·
ack 기반 푸시는 AudioManager 안에 있고, 그게 계층의 실체이기 때문이다.

여기서 지키는 것:
    제지(CRITICAL)는 재생 중인 무엇이든 끊고 먼저 나간다
    재촉(HIGH)은 진행(NORMAL)보다, 진행은 훈수(LOW)보다 먼저 나간다
    2단 발화는 제지 → 설명 순서를 지킨다
    세션이 끝나면 백그라운드 태스크가 남지 않는다
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from agents.base import Intervention
from agents.context import AgentContext
from agents.orchestrator import AgentOrchestrator
from agents.tools import llm, tempo_pool
from agents.tools.llm import LLMClient, LLMResult
from audio.manager import AudioManager
from audio.tts_engine import TTSEngine
from core.audio import AudioPriority
from core.envelope import WSMessage
from core.events import GameEvent


class _SilentClient(LLMClient):
    """LLM이 없는 환경. 규칙 기반 폴백만 도는지 보려고 쓴다."""

    async def complete(self, system: str, user: str, **kwargs: object) -> LLMResult:
        return LLMResult(text=None, ok=False, latency_ms=0.0, error="테스트")

    async def complete_json(self, system: str, user: str, **kwargs: object) -> LLMResult:
        return LLMResult(text=None, ok=False, latency_ms=0.0, error="테스트")


@pytest.fixture(autouse=True)
def _silence_llm():
    llm.set_client(_SilentClient())
    yield
    llm.set_client(None)
    tempo_pool.clear()


@pytest.fixture
def rig() -> tuple[AgentOrchestrator, AudioManager, list[WSMessage]]:
    engine = MagicMock(spec=TTSEngine)
    engine.cache_hit = MagicMock(return_value=Path("/cache/tts/static/fake.wav"))
    engine.synthesize = AsyncMock(return_value=Path("/cache/tts/static/fake.wav"))
    engine.is_available = MagicMock(return_value=True)

    mgr = AudioManager(engine)
    sent: list[WSMessage] = []

    async def cb(m: WSMessage) -> None:
        sent.append(m)

    mgr.attach_broadcast(cb)
    return AgentOrchestrator(mgr), mgr, sent


def _texts(sent: list[WSMessage]) -> list[str]:
    return [m.payload.get("text", "") for m in sent]


def _werewolf_ctx(state: str = "night_seer", **kw: object) -> AgentContext:
    base = {
        "game_type": "werewolf",
        "fsm_state": state,
        "active_player": "p1",
        "players": [{"player_id": "p1", "playername": "성민"}],
        "allowed_actors": ["p1"],
    }
    base.update(kw)
    return AgentContext(**base)  # type: ignore[arg-type]


# ── 우선순위 계층 ─────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_급한_것부터_나간다(rig):
    """큐에 한꺼번에 들어가면 CRITICAL → HIGH → NORMAL → LOW 순이어야 한다."""
    orch, mgr, sent = rig

    # 첫 항목은 즉시 나가버리므로, 자리를 채워두고 나머지를 쌓는다.
    blocker = await mgr.enqueue_tts("자리를 채우는 멘트.", priority=AudioPriority.NORMAL)
    await orch._dispatch(Intervention("strategy", "훈수", AudioPriority.LOW))
    await orch._dispatch(Intervention("progress", "진행", AudioPriority.NORMAL))
    await orch._dispatch(Intervention("tempo", "재촉", AudioPriority.HIGH))

    assert [q.msg.payload["text"] for q in mgr._queue] == ["재촉", "진행", "훈수"]
    await mgr.handle_ack(blocker, "played")


@pytest.mark.anyio
async def test_제지는_재생_중인_말을_끊는다(rig):
    """차례가 아닌 사람이 굴렸는데 안내가 끝나기를 기다릴 수는 없다."""
    orch, mgr, sent = rig
    await orch.on_state_change(_werewolf_ctx(), state_version=1)
    await asyncio.sleep(0)
    playing = len(sent)

    orch._current_ctx = _werewolf_ctx()
    await orch.on_game_event(
        GameEvent(event_type="dice_rolled", actor_id="p9", confidence=1.0, frame_id=0)
    )

    kinds = [m.msg_type for m in sent]
    assert "tts_interrupt" in kinds, "제지가 재생 중인 발화를 끊지 않았다"
    assert len(sent) > playing


# ── 2단 발화 ──────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_제지가_먼저_설명이_나중(rig):
    orch, mgr, sent = rig
    orch._current_ctx = _werewolf_ctx()

    class _Explains(_SilentClient):
        async def complete(self, system, user, **kwargs) -> LLMResult:
            await asyncio.sleep(0.02)  # 생성 지연
            return LLMResult(text="남의 차례에 손대면 안 됩니다.", ok=True, latency_ms=20.0)

    llm.set_client(_Explains())

    await orch.on_game_event(
        GameEvent(event_type="dice_rolled", actor_id="p9", confidence=1.0, frame_id=0)
    )
    first = [t for t in _texts(sent) if t]
    assert first, "제지가 즉시 나가지 않았다"

    # 설명은 뒤따라온다. 앞 발화가 ack되기 전에는 큐에서 기다린다.
    for _ in range(50):
        await asyncio.sleep(0.01)
        if len(mgr._queue) or len(sent) > len(first):
            break
    queued = [q.msg.payload["text"] for q in mgr._queue]
    assert "남의 차례에 손대면 안 됩니다." in (queued + _texts(sent))
    # 제지가 먼저다.
    assert _texts(sent)[0] == first[0]


# ── LLM이 없어도 진행된다 ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_llm이_전부_실패해도_안내는_나간다(rig):
    """LLM이 죽어도 게임은 굴러가야 한다. 이게 폴백의 존재 이유다."""
    orch, mgr, sent = rig

    await orch.on_state_change(_werewolf_ctx("night_seer"), state_version=1)
    for _ in range(20):
        await asyncio.sleep(0.01)

    spoken = [t for t in _texts(sent) if t]
    assert spoken, "LLM이 실패하자 아무 말도 안 나왔다"
    assert llm.get_client().stats()["ok"] == 0  # type: ignore[union-attr]


# ── 빠른 전환 ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_훈수는_한_번에_하나만_돈다(rig):
    """주사위를 빠르게 굴리면 훈수 요청이 겹쳐 쌓인다. 앞의 것은 어차피
    판이 넘어가 버려질 말이므로 취소한다 — 실측으로 10회 전환에 10건이
    동시에 물려 있었고 9건이 폐기됐다."""
    orch, mgr, sent = rig
    orch.set_strategy_enabled(True)

    class _Slow(_SilentClient):
        async def complete(self, system, user, **kwargs) -> LLMResult:
            await asyncio.sleep(1.0)
            return LLMResult(text="훈수", ok=True, latency_ms=1000.0)

    llm.set_client(_Slow())

    def _ctx() -> AgentContext:
        return AgentContext(
            game_type="yacht",
            fsm_state="AWAITING_SCORE",
            active_player=None,
            players=[],
            game_specific={
                "dice_values": [5, 5, 5, 2, 2],
                "roll_count": 3,
                "available_categories": ["full_house"],
            },
        )

    for version in range(1, 6):
        await orch.on_state_change(_ctx(), state_version=version)
        await asyncio.sleep(0.01)
        alive = [t for t in orch._tasks if not t.done()]
        assert len(alive) <= 1, f"훈수 태스크가 {len(alive)}개 겹쳤다"

    orch.stop()
    await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_한마디는_전환이_와도_취소되지_않는다(rig):
    """점수가 확정되면 곧바로 다음 차례로 넘어간다. 여기서 같이 취소하면
    한마디가 매번 사라진다."""
    orch, mgr, sent = rig

    class _Reacts(_SilentClient):
        async def complete(self, system, user, **kwargs) -> LLMResult:
            await asyncio.sleep(0.05)
            return LLMResult(text="오, 대단하네요!", ok=True, latency_ms=50.0)

    llm.set_client(_Reacts())

    scored = AgentContext(
        game_type="yacht",
        fsm_state="AWAITING_ROLL",
        active_player=None,
        players=[],
        game_specific={
            "narration": {
                "line_id": "yacht.score_recorded",
                "params": {"scorer": "성민", "label": "요트", "score": 50},
            }
        },
    )
    await orch.on_state_change(scored, state_version=1)
    # 곧바로 다음 차례로 넘어간다.
    await orch.on_state_change(
        AgentContext(
            game_type="yacht",
            fsm_state="AWAITING_ROLL",
            active_player=None,
            players=[],
            game_specific={},
        ),
        state_version=2,
    )
    for _ in range(50):
        await asyncio.sleep(0.01)
        if "오, 대단하네요!" in _texts(sent) + [q.msg.payload["text"] for q in mgr._queue]:
            break

    assert "오, 대단하네요!" in _texts(sent) + [q.msg.payload["text"] for q in mgr._queue]


# ── 세션 정리 ─────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_세션이_끝나면_백그라운드가_남지_않는다(rig):
    """죽은 세션의 태스크가 살아남으면 닫힌 소켓으로 발화를 밀어 넣는다."""
    orch, mgr, sent = rig

    class _Slow(_SilentClient):
        async def complete(self, system, user, **kwargs) -> LLMResult:
            await asyncio.sleep(5)
            return LLMResult(text="늦은 말", ok=True, latency_ms=5000.0)

    llm.set_client(_Slow())
    orch.set_strategy_enabled(True)

    await orch.on_state_change(
        AgentContext(
            game_type="yacht",
            fsm_state="AWAITING_SCORE",
            active_player=None,
            players=[],
            turn_timeout=30.0,
            game_specific={
                "dice_values": [5, 5, 5, 2, 2],
                "roll_count": 3,
                "available_categories": ["full_house"],
            },
        ),
        state_version=1,
    )
    await asyncio.sleep(0.01)
    assert orch._tasks, "백그라운드 태스크가 안 만들어졌다"

    orch.stop()
    await asyncio.sleep(0.01)

    assert not orch._tasks
    assert orch._tempo._task is None


@pytest.mark.anyio
async def test_새_판을_시작하면_네_에이전트가_모두_잊는다(rig):
    """앞 판의 기억이 남으면 첫 위반·첫 조언이 조용히 삼켜진다."""
    orch, _, _ = rig
    orch._progress._last_state = "night_seer"
    orch._progress._last_reaction = "뭔가"
    orch._rules._last_key = "wrong_turn:p9"
    orch._strategy._seen_coach_hints.add("roll")

    orch.reset_for_new_game()

    assert orch._progress._last_state == ""
    assert orch._progress._last_reaction == ""
    assert orch._rules._last_key == ""
    assert not orch._strategy._seen_coach_hints
