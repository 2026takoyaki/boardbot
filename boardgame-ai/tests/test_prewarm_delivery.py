"""말투가 다른 발화도 미리 합성해 둔다.

캐시 키에는 speaking_rate·emotion이 들어간다. 그래서 기본 말투로 데워둔
파일은 심판 말투 발화에 쓰이지 못한다 — 같은 문장이라도 키가 다르다.

이걸 놓치면 규칙 제지가 매번 캐시 미스가 된다. 2단 발화는 "1단은 캐시라
0지연"을 전제로 세워져 있으므로, 그 전제가 깨지면 설계 전체가 무너진다.
가장 급해야 할 발화가 가장 느려지는데 소리로만 드러나서 알아채기 어렵다.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.personas import get_persona
from agents.tools import lines
from audio.manager import AudioManager
from audio.tts_engine import _make_cache_key


class _RecordingEngine:
    """합성한 (문장, 캐시키)를 기록만 하는 가짜 엔진."""

    def __init__(self) -> None:
        self.synthesized: list[tuple[str, str]] = []

    def is_available(self, voice=None) -> bool:
        return True

    def cache_hit(self, text, voice, layer, session_id=None):
        return None  # 항상 미스 → 전부 합성하게 만든다

    async def synthesize(self, text, voice, layer, session_id=None):
        from pathlib import Path

        self.synthesized.append((text, _make_cache_key(text, voice)))
        return Path(f"/fake/{_make_cache_key(text, voice)}.wav")


@pytest.fixture
def persona():
    p = get_persona("chungcheong")
    lines.use_persona(p.id)
    return p


def _catalog(mgr: AudioManager) -> None:
    mgr.set_line_catalog(
        lines.static_texts(),
        lines.session_templates(),
        lines.delivery_static(),
        lines.delivery_templates(),
    )


@pytest.mark.anyio
async def test_심판_말투_고정문장이_그_말투로_합성된다(persona):
    engine = _RecordingEngine()
    mgr = AudioManager(engine)  # type: ignore[arg-type]
    _catalog(mgr)

    await mgr.set_persona(persona, prewarm=True)

    done = {key for _, key in engine.synthesized}
    referee_lines = lines.delivery_static()["referee"]
    assert referee_lines, "심판 말투 고정 문장이 없다 — 분류가 깨졌다"

    for text in referee_lines:
        base_key = _make_cache_key(text, persona.voice_for())
        ref_key = _make_cache_key(text, persona.voice_for("referee"))
        assert base_key != ref_key, "말투가 같으면 이 테스트는 의미가 없다"
        assert base_key in done, f"기본 말투가 안 데워졌다: {text}"
        assert ref_key in done, f"심판 말투가 안 데워졌다: {text}"


@pytest.mark.anyio
async def test_말투가_없으면_기본만_합성한다(persona):
    """말투별 목록을 안 주면 예전대로 동작해야 한다."""
    engine = _RecordingEngine()
    mgr = AudioManager(engine)  # type: ignore[arg-type]
    mgr.set_line_catalog(lines.static_texts(), lines.session_templates())

    await mgr.set_persona(persona, prewarm=True)

    text = lines.delivery_static()["referee"][0]
    done = {key for _, key in engine.synthesized}
    assert _make_cache_key(text, persona.voice_for()) in done
    assert _make_cache_key(text, persona.voice_for("referee")) not in done


@pytest.mark.anyio
async def test_이름을_채운_제지도_심판_말투로_합성된다(persona):
    """'지금은 성민님 차례입니다'는 세션 계층이면서 심판 말투다."""
    engine = _RecordingEngine()
    mgr = AudioManager(engine)  # type: ignore[arg-type]
    _catalog(mgr)
    # 안 걸면 fallback 페르소나로 합성된다 — 그쪽은 말투 구분이 없어 통과해버린다.
    await mgr.set_persona(persona, prewarm=False)

    templates = lines.delivery_templates()["referee"]
    assert templates, "심판 말투 템플릿이 없다 — 분류가 깨졌다"

    mgr.prewarm_session_async(["성민"])

    # prewarm_session_async는 태스크를 띄운다. 기본 패스가 먼저 끝나므로
    # "뭐라도 합성됐다"로 기다리면 심판 패스를 놓친다. 그 키를 직접 기다린다.
    filled = lines.fill(templates[0], player="성민")
    want = _make_cache_key(filled, persona.voice_for("referee"))
    for _ in range(100):
        await asyncio.sleep(0.01)
        if want in {key for _, key in engine.synthesized}:
            break

    done = {key for _, key in engine.synthesized}
    assert filled in {text for text, _ in engine.synthesized}, "이름을 채운 문장이 아예 안 나왔다"
    assert want in done, "심판 말투로는 안 데워졌다"
