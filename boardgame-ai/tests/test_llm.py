"""LLM 공용 클라이언트.

실패해도 게임이 멈추면 안 되고, 왜 실패했는지는 남아야 한다.
실제로 겪은 사고: strategy_agent가 max_tokens를 보내 매번 400을 받았는데
except가 삼켜서 "LLM이 그냥 안 붙은 것"처럼 보였다.

실제 API를 부르지 않는다 — 가짜 응답을 끼워 넣어 경로만 확인한다.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from agents.tools import llm
from agents.tools.llm import LLMClient, sanitize_for_tts


class _FakeCompletions:
    def __init__(self, outer: _FakeOpenAI) -> None:
        self._outer = outer

    async def create(self, **kwargs: object) -> object:
        self._outer.calls.append(kwargs)
        if self._outer.raises is not None:
            raise self._outer.raises
        if self._outer.delay:
            await asyncio.sleep(self._outer.delay)
        return self._outer.response


class _FakeOpenAI:
    """openai.AsyncOpenAI의 호출 표면만 흉내낸다."""

    def __init__(self, content: str | None = "안녕하세요.", **kw: object) -> None:
        self.calls: list[dict] = []
        self.raises: Exception | None = kw.get("raises")  # type: ignore[assignment]
        self.delay: float = float(kw.get("delay", 0))  # type: ignore[arg-type]
        self.response = type(
            "R",
            (),
            {
                "choices": [
                    type("C", (), {"message": type("M", (), {"content": content})()})()
                ],
                "usage": type("U", (), {"completion_tokens": 7})(),
            },
        )()
        self.chat = type("Chat", (), {"completions": _FakeCompletions(self)})()


def _client(monkeypatch, fake: _FakeOpenAI, **kw: object) -> LLMClient:
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    c = LLMClient(**kw)  # type: ignore[arg-type]
    c._client = fake  # type: ignore[attr-defined]
    return c


# ── 파라미터 ───────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_max_completion_tokens를_보낸다(monkeypatch) -> None:
    """max_tokens를 보내면 최신 모델이 400으로 거부한다. 실제로 그래서 LLM이
    한 번도 동작하지 않았다."""
    fake = _FakeOpenAI()
    c = _client(monkeypatch, fake)
    await c.complete("sys", "user", max_tokens=50)

    assert "max_completion_tokens" in fake.calls[0]
    assert "max_tokens" not in fake.calls[0]


@pytest.mark.anyio
async def test_json_모드는_response_format을_붙인다(monkeypatch) -> None:
    fake = _FakeOpenAI(content='{"a": 1}')
    c = _client(monkeypatch, fake)
    await c.complete_json("sys", "user")
    assert fake.calls[0]["response_format"] == {"type": "json_object"}


@pytest.mark.anyio
async def test_json_응답은_정화하지_않는다(monkeypatch) -> None:
    """마크다운 제거 정규식이 대괄호를 지운다. JSON에 걸면 배열이 깨진다 —
    실제로 tempo 변형이 전부 이 때문에 파싱 실패로 버려졌다."""
    payload = '{"tempo.half": ["반 지났어요.", "절반이요."]}'
    c = _client(monkeypatch, _FakeOpenAI(content=payload))
    result = await c.complete_json("sys", "user")

    assert result.text is not None
    assert json.loads(result.text) == {"tempo.half": ["반 지났어요.", "절반이요."]}


@pytest.mark.anyio
async def test_코드펜스로_감싸_와도_읽는다(monkeypatch) -> None:
    """response_format을 줘도 ```json으로 감싸 오는 경우가 있다."""
    c = _client(monkeypatch, _FakeOpenAI(content='```json\n{"a": [1, 2]}\n```'))
    result = await c.complete_json("sys", "user")

    assert result.text is not None
    assert json.loads(result.text) == {"a": [1, 2]}


# ── 실패해도 죽지 않는다 ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_예외가_나도_예외를_던지지_않는다(monkeypatch) -> None:
    """멘트 하나 때문에 게임이 멈추면 안 된다."""
    c = _client(monkeypatch, _FakeOpenAI(raises=RuntimeError("400 Bad Request")))
    result = await c.complete("sys", "user")

    assert result.ok is False
    assert result.text is None
    assert "400" in (result.error or "")


@pytest.mark.anyio
async def test_타임아웃은_포기하고_돌아온다(monkeypatch) -> None:
    c = _client(monkeypatch, _FakeOpenAI(delay=0.5), timeout=0.05)
    result = await c.complete("sys", "user")

    assert result.ok is False
    assert result.error == "타임아웃"
    assert c.stats()["timeouts"] == 1


@pytest.mark.anyio
async def test_content가_None이어도_죽지_않는다(monkeypatch) -> None:
    """토큰 예산을 다 쓰면 content가 None으로 온다. .strip()을 바로 부르면
    AttributeError로 죽는다 — 옛 코드가 그랬다."""
    c = _client(monkeypatch, _FakeOpenAI(content=None))
    result = await c.complete("sys", "user")

    assert result.ok is False
    assert result.error == "빈 응답"


@pytest.mark.anyio
async def test_키가_없으면_부르지_않는다(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = LLMClient()
    result = await c.complete("sys", "user")

    assert result.ok is False
    assert "OPENAI_API_KEY" in (result.error or "")


# ── 출력 정리 ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("**밤입니다**", "밤입니다"),
        ("밤입니다 🌙", "밤입니다"),
        ("밤입니다.\n눈 감으세요.", "밤입니다. 눈 감으세요."),
        ('"밤입니다."', "밤입니다."),
        ("  밤입니다.  ", "밤입니다."),
    ],
)
def test_TTS가_읽으면_안_되는_것을_걷어낸다(raw: str, expected: str) -> None:
    """출력이 곧 TTS 입력이다. 프롬프트만 믿으면 '별표 별표'가 읽힌다."""
    assert sanitize_for_tts(raw) == expected


@pytest.mark.anyio
async def test_응답도_정리해서_돌려준다(monkeypatch) -> None:
    c = _client(monkeypatch, _FakeOpenAI(content="**밤입니다**\n눈 감으세요."))
    result = await c.complete("sys", "user")
    assert result.text == "밤입니다 눈 감으세요."


# ── 관측 ───────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_실패_사유가_남는다(monkeypatch) -> None:
    """조용히 폴백하면 왜 LLM이 안 붙는지 알 방법이 없다."""
    c = _client(monkeypatch, _FakeOpenAI(raises=RuntimeError("boom")))
    await c.complete("sys", "user", tag="strategy.yacht")

    stats = c.stats()
    assert stats["failed"] == 1
    assert "boom" in stats["last_error"]
    assert stats["by_tag"]["strategy.yacht"] == 1


@pytest.mark.anyio
async def test_클라이언트를_재사용한다(monkeypatch) -> None:
    """호출마다 새로 만들면 커넥션 풀이 논다."""
    fake = _FakeOpenAI()
    c = _client(monkeypatch, fake)
    await c.complete("sys", "user")
    await c.complete("sys", "user")
    assert len(fake.calls) == 2


def test_싱글톤() -> None:
    llm.set_client(None)
    assert llm.get_client() is llm.get_client()
    llm.set_client(None)


def test_키가_없어도_상태_조회가_죽지_않는다(monkeypatch) -> None:
    """AsyncOpenAI()는 키가 없으면 생성 자체가 예외를 던진다. 막지 않으면
    'LLM 되나?' 물어보는 것만으로 서버가 터진다."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    c = LLMClient()

    assert c.is_available() is False
    assert "OPENAI_API_KEY" in c.unavailable_reason()
    assert c.stats()["available"] is False
