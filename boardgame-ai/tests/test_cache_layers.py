"""캐시 계층 — 미리 만들어 둘 수 있는 문장을 실제로 미리 만드는가.

이게 어긋나면 게임은 정상 진행되지만 매 페이즈 첫 마디마다 합성 지연이 붙는다.
증상이 조용해서(음성은 나온다) 테스트가 없으면 한참 뒤에야 알아챈다.

실제로 겪은 사고: 페르소나가 문장을 바꾸는데 prewarm 목록은 중립 원문을 들고
있어서, 페르소나를 켜면 static 캐시가 0줄이 됐다.
"""

from __future__ import annotations

import pytest

from agents.personas import PERSONAS
from agents.tools import lines
from audio.manager import AudioManager
from audio.tts_engine import TTSEngine
from backend.persona_control import apply_persona

# 슬롯을 가진 모든 문장을 렌더할 수 있도록 값을 넉넉히 준다.
_PARAMS = {
    "player": "성민", "scorer": "성민", "next": "형승", "label": "풀하우스",
    "score": 25, "values": "1, 2, 3", "remaining": "두 번", "count": "다섯",
    "headline": "성민", "face": "3", "run": "3-4-5", "triple": "3", "pair": "5",
}


@pytest.fixture(autouse=True)
def _reset():
    yield
    lines.use_persona(None)


def _layer_counts(mgr: AudioManager) -> dict[str, int]:
    counts: dict[str, int] = {}
    for line_id in lines.LINES:
        text = lines.render(line_id, **_PARAMS) or ""
        layer, _ = mgr._layer_for(text)
        counts[layer] = counts.get(layer, 0) + 1
    return counts


# ── 계층 판정 ──────────────────────────────────────────────────────────────────


def test_슬롯이_없으면_static() -> None:
    """그대로 나가는 문장은 부팅 때 만들어 둘 수 있다."""
    texts = lines.static_texts()
    assert texts
    assert all("{" not in t for t in texts)


def test_이름_슬롯만_있으면_session() -> None:
    """이름만 채우면 되는 문장은 좌석이 정해지면 만들어 둘 수 있다."""
    for template in lines.session_templates():
        assert "{player}" in template
        # 슬롯이 여럿이면 값 조합이 매번 달라 미리 만들 수 없다.
        assert template.count("{") == 1


def test_점수_발표는_session이_아니다() -> None:
    """주사위 값·점수는 매번 달라 미리 만들 수 없다."""
    assert lines.LINES["yacht.score_recorded"] not in lines.session_templates()


# ── 페르소나를 바꿔도 유지되는가 ──────────────────────────────────────────────


@pytest.mark.anyio
@pytest.mark.parametrize("persona_id", sorted(PERSONAS))
async def test_페르소나를_켜도_static_캐시가_살아있다(persona_id: str) -> None:
    """페르소나가 문장을 바꾸는데 prewarm 목록이 중립 원문을 들고 있으면
    static이 0줄이 되고 모든 발화가 즉석 합성된다."""
    mgr = AudioManager(TTSEngine())
    await apply_persona(persona_id, mgr, prewarm=False)

    counts = _layer_counts(mgr)
    assert counts.get("static", 0) > 50, f"{persona_id}: static이 너무 적다 {counts}"


@pytest.mark.anyio
async def test_좌석이_등록되면_이름_문장도_캐시된다() -> None:
    mgr = AudioManager(TTSEngine())
    await apply_persona(sorted(PERSONAS)[0], mgr, prewarm=False)

    before = _layer_counts(mgr)
    mgr.prewarm_session_async(["성민", "형승"])
    after = _layer_counts(mgr)

    assert before.get("session", 0) == 0
    assert after.get("session", 0) > 0
    assert after["dynamic"] < before["dynamic"]


@pytest.mark.anyio
async def test_페르소나를_바꾸면_옛_이름_문장은_버린다() -> None:
    """옛 말투로 채워둔 문장이 남아 있으면 새 페르소나에서 잘못 hit된다."""
    mgr = AudioManager(TTSEngine())
    first, second = sorted(PERSONAS)[0], sorted(PERSONAS)[1]

    await apply_persona(first, mgr, prewarm=False)
    mgr.prewarm_session_async(["성민"])
    assert _layer_counts(mgr).get("session", 0) > 0

    await apply_persona(second, mgr, prewarm=False)
    assert _layer_counts(mgr).get("session", 0) == 0


# ── prewarm이 실제로 발화될 문장을 만드는가 ──────────────────────────────────


@pytest.mark.anyio
async def test_prewarm_대상이_실제_발화_문장과_같다() -> None:
    """prewarm이 만든 것과 런타임에 찾는 것이 다르면 캐시가 통째로 논다."""
    mgr = AudioManager(TTSEngine())
    await apply_persona(sorted(PERSONAS)[0], mgr, prewarm=False)

    prewarmed = set(lines.static_texts())
    spoken = {
        lines.render(line_id, **_PARAMS) or ""
        for line_id in lines.LINES
        if "{" not in (lines.get(line_id) or "")
    }
    spoken.discard("")

    assert spoken <= prewarmed, f"발화되는데 안 데워지는 문장: {spoken - prewarmed}"
