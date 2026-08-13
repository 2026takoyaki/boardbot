"""TTS 엔진 — 캐시와 엔진 어댑터의 경계.

합성은 엔진 어댑터(audio/tts/)가, 캐시·동시성·벤치마크 훅은 여기가 맡는다.
그 경계가 어긋나면 "캐시가 있을 때만 죽는" 식의 잠복 버그가 생긴다.
"""

from __future__ import annotations

import pytest

from audio.tts_engine import TTSEngine, _make_cache_key
from core.persona import VoiceConfig


class _FakeProvider:
    """합성 결과를 정해두고 호출을 기록한다."""

    name = "fake"
    audio_ext = "wav"

    def __init__(self, available: bool = True) -> None:
        self._available = available
        self.calls: list[tuple[str, VoiceConfig]] = []

    def is_available(self) -> bool:
        return self._available

    def unavailable_reason(self) -> str:
        return "" if self._available else "테스트용 비활성"

    def synthesize_sync(self, text: str, voice: VoiceConfig) -> bytes:
        self.calls.append((text, voice))
        return b"RIFF-fake-audio"


@pytest.fixture
def engine(tmp_path, monkeypatch):
    import audio.tts_engine as mod

    monkeypatch.setattr(mod, "STATIC_CACHE_DIR", tmp_path / "static")
    monkeypatch.setattr(mod, "DYNAMIC_CACHE_DIR", tmp_path / "dynamic")
    monkeypatch.setattr(mod, "SESSION_CACHE_DIR", tmp_path / "session")
    return TTSEngine()


def _use(engine: TTSEngine, provider: _FakeProvider) -> VoiceConfig:
    voice = VoiceConfig(name="v1", provider="fake")
    engine._providers["fake"] = provider  # type: ignore[attr-defined]
    return voice


# ── 캐시 ───────────────────────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_두_번째_호출은_합성하지_않는다(engine) -> None:
    provider = _FakeProvider()
    voice = _use(engine, provider)

    first = await engine.synthesize("밤이다", voice, "static")
    second = await engine.synthesize("밤이다", voice, "static")

    assert first == second
    assert len(provider.calls) == 1


@pytest.mark.anyio
async def test_캐시가_있어도_조회가_죽지_않는다(engine) -> None:
    """벤치마크 훅이 사라졌을 때 여기가 NameError로 죽는다. 실제로 겪었다 —
    캐시가 비어 있으면 이 경로를 안 지나가서 다른 테스트로는 안 잡힌다."""
    provider = _FakeProvider()
    voice = _use(engine, provider)
    await engine.synthesize("밤이다", voice, "static")

    hit = engine.cache_hit("밤이다", voice, "static")

    assert hit is not None and hit.exists()


@pytest.mark.anyio
async def test_합성_실패는_None을_돌려준다(engine) -> None:
    """엔진이 죽어도 게임은 계속된다. 그 멘트만 자막으로 나간다."""
    provider = _FakeProvider(available=False)
    voice = _use(engine, provider)

    assert await engine.synthesize("밤이다", voice, "static") is None
    assert provider.calls == []


@pytest.mark.anyio
async def test_확장자는_엔진이_정한다(engine) -> None:
    provider = _FakeProvider()
    voice = _use(engine, provider)
    path = await engine.synthesize("밤이다", voice, "static")
    assert path is not None and path.suffix == ".wav"


@pytest.mark.anyio
async def test_임시파일을_남기지_않는다(engine, tmp_path) -> None:
    """부분 쓰기로 깨진 캐시가 남으면 그 멘트가 영영 깨진 채로 재생된다."""
    provider = _FakeProvider()
    voice = _use(engine, provider)
    await engine.synthesize("밤이다", voice, "static")

    assert list((tmp_path / "static").glob("*.tmp")) == []


# ── 캐시 키 ────────────────────────────────────────────────────────────────────


def test_엔진이_다르면_키가_다르다() -> None:
    """엔진을 갈아끼웠는데 옛 파일이 hit되면 목소리가 안 바뀐다."""
    a = VoiceConfig(name="v1", provider="typecast")
    b = VoiceConfig(name="v1", provider="other")
    assert _make_cache_key("밤", a) != _make_cache_key("밤", b)


def test_감정이_다르면_키가_다르다() -> None:
    """같은 문장을 화난 톤과 기쁜 톤으로 각각 합성해야 한다."""
    a = VoiceConfig(name="v1", emotion="angry")
    b = VoiceConfig(name="v1", emotion="happy")
    assert _make_cache_key("밤", a) != _make_cache_key("밤", b)


def test_모델이_다르면_키가_다르다() -> None:
    a = VoiceConfig(name="v1", model="ssfm-v30")
    b = VoiceConfig(name="v1", model="ssfm-v21")
    assert _make_cache_key("밤", a) != _make_cache_key("밤", b)


def test_같은_설정이면_키가_같다() -> None:
    a = VoiceConfig(name="v1", speaking_rate=1.1, emotion="angry")
    b = VoiceConfig(name="v1", speaking_rate=1.1, emotion="angry")
    assert _make_cache_key("밤", a) == _make_cache_key("밤", b)


# ── 어댑터 선택 ────────────────────────────────────────────────────────────────


def test_모르는_엔진이면_기본_엔진으로_떨어진다(engine) -> None:
    """엔진 이름 오타로 서버가 죽으면 안 된다."""
    from audio.tts.base import DEFAULT_PROVIDER

    provider = engine.provider_for(VoiceConfig(name="v1", provider="없는엔진"))
    assert provider.name == DEFAULT_PROVIDER


def test_어댑터를_재사용한다(engine) -> None:
    voice = VoiceConfig(name="v1")
    assert engine.provider_for(voice) is engine.provider_for(voice)
