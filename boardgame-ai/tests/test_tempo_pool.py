"""템포 변형 풀.

여기가 지켜야 할 것은 두 가지다.
  1. LLM이 죽든 이상한 걸 뱉든 재촉은 반드시 나온다 — 원문으로라도.
  2. 미리 만든 문장은 전부 prewarm 목록으로 나가야 한다. 안 그러면 변형이
     나올 때마다 합성 지연이 붙어 안 만드느니만 못하다.

실제 API를 부르지 않는다.
"""

from __future__ import annotations

import json

import pytest

from agents.personas import get_persona
from agents.tools import lines, llm, tempo_pool
from agents.tools.llm import LLMClient, LLMResult


class _StubClient(LLMClient):
    """complete_json만 갈아끼운 가짜 클라이언트."""

    def __init__(self, payload: str | None, ok: bool = True) -> None:
        super().__init__()
        self._payload = payload
        self._ok = ok

    async def complete_json(self, system: str, user: str, **kwargs: object) -> LLMResult:
        return LLMResult(
            text=self._payload,
            ok=self._ok,
            latency_ms=1.0,
            error=None if self._ok else "테스트 실패",
        )


@pytest.fixture(autouse=True)
def _clean():
    yield
    tempo_pool.clear()
    llm.set_client(None)


def _persona():
    return get_persona(None)


@pytest.mark.anyio
async def test_변형이_풀에_들어가고_prewarm_목록으로_나온다():
    llm.set_client(
        _StubClient(
            json.dumps(
                {
                    "tempo.half": ["반 지났어요.", "절반이요."],
                    "tempo.hurry": ["슬슬 정하시죠."],
                },
                ensure_ascii=False,
            )
        )
    )

    texts = await tempo_pool.regenerate(_persona())

    variants = tempo_pool.stats()["variants"]
    assert variants["tempo.half"] == 3  # 원문 + 변형 2
    assert variants["tempo.hurry"] == 2
    # 만든 문장은 하나도 빠짐없이 prewarm 목록에 실려야 한다.
    assert "반 지났어요." in texts
    assert len(texts) == sum(variants.values())


@pytest.mark.anyio
async def test_llm이_실패해도_원문으로_재촉한다():
    llm.set_client(_StubClient(None, ok=False))

    await tempo_pool.regenerate(_persona())

    for line_id in tempo_pool.POOL_LINE_IDS:
        assert tempo_pool.pick(line_id) == lines.get(line_id)


@pytest.mark.anyio
async def test_깨진_json은_원문만_남긴다():
    llm.set_client(_StubClient("{이건 JSON이 아니다"))

    await tempo_pool.regenerate(_persona())

    assert all(n == 1 for n in tempo_pool.stats()["variants"].values())


@pytest.mark.anyio
async def test_읽을_수_없는_변형은_버린다():
    llm.set_client(
        _StubClient(
            json.dumps(
                {
                    "tempo.half": [
                        "",  # 빈 문장
                        "{player}님 서두르세요",  # 채워줄 사람이 없는 슬롯
                        "재" * 60,  # 재촉이라기엔 너무 긺
                        42,  # 문자열이 아님
                        "반 지났어요.",  # 이것만 통과
                    ],
                },
                ensure_ascii=False,
            )
        )
    )

    await tempo_pool.regenerate(_persona())

    assert tempo_pool.stats()["variants"]["tempo.half"] == 2  # 원문 + 1


def test_풀이_비면_고정_멘트로_떨어진다():
    tempo_pool.clear()
    assert tempo_pool.pick("tempo.half") == lines.get("tempo.half")
    assert tempo_pool.pick("없는.line_id") is None


@pytest.mark.anyio
async def test_같은_문장을_연속으로_뽑지_않는다():
    llm.set_client(_StubClient(json.dumps({"tempo.half": ["가", "나", "다"]}, ensure_ascii=False)))
    await tempo_pool.regenerate(_persona())

    picks = [tempo_pool.pick("tempo.half") for _ in range(20)]
    assert all(a != b for a, b in zip(picks, picks[1:], strict=False))


@pytest.mark.anyio
async def test_페르소나를_바꾸면_이전_변형이_남지_않는다():
    llm.set_client(_StubClient(json.dumps({"tempo.half": ["옛말투"]}, ensure_ascii=False)))
    await tempo_pool.regenerate(_persona())

    llm.set_client(_StubClient(json.dumps({"tempo.half": ["새말투"]}, ensure_ascii=False)))
    await tempo_pool.regenerate(_persona())

    assert "옛말투" not in tempo_pool.stats()["variants"]
    bucket_size = tempo_pool.stats()["variants"]["tempo.half"]
    assert bucket_size == 2  # 원문 + 새 변형 하나뿐
