"""페르소나 전환이 재촉 변형 생성을 기다리지 않는다.

변형을 만드는 LLM 호출만 10초가 걸린다. 이것을 전환 경로에서 await하면
서버 부팅이 그만큼 늦어지는데, 정작 재촉이 필요한 시점은 한참 뒤다.
그래서 먼저 뜨고 나중에 더한다.

늦게 더하더라도 static 목록에는 반드시 들어가야 한다. 안 들어가면 계층
판정이 dynamic으로 떨어져, 미리 만들어 둔 의미가 없어진다.
"""

from __future__ import annotations

import asyncio
import json
import time

import pytest

from agents.tools import lines, llm, tempo_pool
from agents.tools.llm import LLMClient, LLMResult
from backend import persona_control


class _SlowClient(LLMClient):
    """느린 LLM. 전환이 이걸 기다리는지 보려고 일부러 지연을 준다."""

    def __init__(self, delay: float = 0.3) -> None:
        super().__init__()
        self._delay = delay

    async def complete_json(self, system: str, user: str, **kwargs: object) -> LLMResult:
        await asyncio.sleep(self._delay)
        return LLMResult(
            text=json.dumps({"tempo.half": ["반 지났슈"]}, ensure_ascii=False),
            ok=True,
            latency_ms=self._delay * 1000,
        )


class _FakeAudio:
    def __init__(self) -> None:
        self.static: set[str] = set()
        self.added: list[list[str]] = []

    def set_line_catalog(
        self,
        static_texts,
        session_templates=(),
        delivery_static=None,
        delivery_templates=None,
    ) -> None:
        self.static = set(static_texts)
        self.delivery_static = dict(delivery_static or {})

    async def set_persona(self, persona, prewarm: bool = True) -> dict[str, int]:
        return {"total": len(self.static)}

    async def add_static_texts(self, texts, prewarm: bool = True) -> dict[str, int]:
        items = list(texts)
        self.added.append(items)
        self.static |= set(items)
        return {"total": len(items)}


@pytest.fixture(autouse=True)
def _clean():
    yield
    task = persona_control._tempo_task
    if task is not None and not task.done():
        task.cancel()
    persona_control._tempo_task = None
    tempo_pool.clear()
    llm.set_client(None)


async def _settle() -> None:
    """뒤에서 도는 변형 준비가 끝날 때까지."""
    task = persona_control._tempo_task
    assert task is not None
    await task


@pytest.mark.anyio
async def test_전환은_변형_생성을_기다리지_않는다():
    llm.set_client(_SlowClient(delay=0.3))
    audio = _FakeAudio()

    started = time.monotonic()
    await persona_control.apply_persona("chungcheong", audio)  # type: ignore[arg-type]
    elapsed = time.monotonic() - started

    assert elapsed < 0.1, f"전환이 변형 생성을 기다렸다 ({elapsed:.2f}s)"
    await _settle()


@pytest.mark.anyio
async def test_변형은_나중에_static_목록에_들어간다():
    llm.set_client(_SlowClient(delay=0.05))
    audio = _FakeAudio()

    await persona_control.apply_persona("chungcheong", audio)  # type: ignore[arg-type]
    assert audio.added == []  # 아직은 없다

    await _settle()

    assert audio.added, "변형이 static 목록에 더해지지 않았다"
    assert "반 지났슈" in audio.static


@pytest.mark.anyio
async def test_전환_중에_또_바꾸면_앞_작업은_버려진다():
    """옛 페르소나 목소리로 합성한 문장이 뒤늦게 얹히면 두 말투가 섞인다."""
    llm.set_client(_SlowClient(delay=0.3))
    audio = _FakeAudio()

    await persona_control.apply_persona("chungcheong", audio)  # type: ignore[arg-type]
    first = persona_control._tempo_task
    assert first is not None

    llm.set_client(_SlowClient(delay=0.01))
    await persona_control.apply_persona("angry", audio)  # type: ignore[arg-type]

    # 앞 작업은 취소되어 아무것도 얹지 못한다.
    with pytest.raises(asyncio.CancelledError):
        await first
    assert "반 지났슈" not in audio.static

    await _settle()
    assert lines.active_persona_id() == "angry"


@pytest.mark.anyio
async def test_prewarm이_꺼져_있으면_아예_만들지_않는다():
    """부팅 시 TTS를 못 쓰는 상황. 합성할 수 없는 문장을 만들어봐야 소용없다."""
    llm.set_client(_SlowClient(delay=0.05))
    audio = _FakeAudio()

    await persona_control.apply_persona("chungcheong", audio, prewarm=False)  # type: ignore[arg-type]

    assert persona_control._tempo_task is None
    assert tempo_pool.stats()["variants"] == {}
