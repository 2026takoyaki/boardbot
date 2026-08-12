"""페르소나 — 목소리의 소유자.

지키는 것:
1. 누가 말하든 페르소나의 목소리 하나로 나간다 (에이전트마다 다른 사람이 아님).
2. 말투는 상황에 따라 갈리되 목소리 이름은 그대로다.
3. 페르소나를 바꾸면 캐시 키가 달라진다 — prewarm이 따라와야 한다는 근거.
"""

from __future__ import annotations

import json

import pytest

from agents.personas import DEFAULT_PERSONA_ID, PERSONAS, get_persona
from agents.tools import lines
from audio.manager import AudioManager
from audio.tts_engine import TTSEngine, _make_cache_key
from backend.persona_control import apply_persona, catalog_message
from core.audio import TTSRequest
from core.constants import AgentRole
from core.persona import DELIVERY_EXCITED, Delivery, Persona


def _persona(**kwargs: object) -> Persona:
    defaults: dict[str, object] = {
        "id": "test",
        "display_name": "테스트",
        "voice_name": "ko-KR-Neural2-A",
        "base": Delivery(speaking_rate=1.1),
        "by_role": {
            AgentRole.REFEREE.value: Delivery(speaking_rate=0.9),
            DELIVERY_EXCITED: Delivery(speaking_rate=1.2),
        },
    }
    defaults.update(kwargs)
    return Persona(**defaults)  # type: ignore[arg-type]


# ── 1. 목소리는 하나, 말투만 갈린다 ────────────────────────────────────────────


def test_역할이_달라도_목소리_이름은_같다() -> None:
    """에이전트마다 목소리를 다르게 주면 네 사람이 번갈아 떠드는 것처럼 들린다."""
    p = _persona()
    names = {
        p.voice_for(role).name
        for role in (None, AgentRole.NARRATOR.value, AgentRole.REFEREE.value, DELIVERY_EXCITED)
    }
    assert names == {"ko-KR-Neural2-A"}


def test_역할에_따라_말투가_갈린다() -> None:
    p = _persona()
    assert p.voice_for().speaking_rate == 1.1
    assert p.voice_for(AgentRole.REFEREE.value).speaking_rate == 0.9
    assert p.voice_for(DELIVERY_EXCITED).speaking_rate == 1.2


def test_따로_정하지_않은_역할은_기본_말투() -> None:
    """다르게 할 것만 적으면 되도록. 전부 나열하게 하면 하나 빠뜨렸을 때 티가 안 난다."""
    p = _persona()
    assert p.voice_for(AgentRole.TEMPO.value) == p.voice_for()
    assert p.voice_for("존재하지_않는_역할") == p.voice_for()


# ── 2. AudioManager 연동 ──────────────────────────────────────────────────────


def _request(text: str, agent: str) -> TTSRequest:
    return TTSRequest(text=text, agent=agent, playback_id="pb")


def test_매니저가_페르소나_목소리로_합성한다() -> None:
    mgr = AudioManager(TTSEngine(), _persona())
    referee = mgr._voice_for(_request("잠깐만요", AgentRole.REFEREE.value))
    narrator = mgr._voice_for(_request("밤이 되었습니다", AgentRole.NARRATOR.value))

    assert referee.name == narrator.name == "ko-KR-Neural2-A"
    assert referee.speaking_rate < narrator.speaking_rate


def test_페르소나를_주입하지_않아도_죽지_않는다() -> None:
    """목소리 조회가 죽으면 발화가 통째로 사라진다. 합성이 실패하더라도
    조회 자체는 예외 없이 끝나야 자막이라도 나간다."""
    mgr = AudioManager(TTSEngine())
    voice = mgr._voice_for(_request("아무 말", AgentRole.NARRATOR.value))
    assert voice.provider


@pytest.mark.anyio
async def test_페르소나를_바꾸면_합성_설정이_바뀐다() -> None:
    """voice_id를 아직 안 채운 상태에서도 말투(속도·감정)는 이미 다르다."""
    mgr = AudioManager(TTSEngine(), _persona(voice_name="v1", base=Delivery(1.0)))
    before = mgr._voice_for(_request("안녕", AgentRole.NARRATOR.value))
    # prewarm=False: 합성 없이 설정만 교체 (API 키 없이도 검증 가능)
    await mgr.set_persona(_persona(voice_name="v2", base=Delivery(1.4)), prewarm=False)
    after = mgr._voice_for(_request("안녕", AgentRole.NARRATOR.value))

    assert (before.name, before.speaking_rate) != (after.name, after.speaking_rate)


# ── 3. 캐시 정합성 ────────────────────────────────────────────────────────────


def test_목소리가_다르면_캐시_키가_다르다() -> None:
    """같은 문장이라도 목소리가 다르면 다른 파일이어야 한다. 안 그러면 페르소나를
    바꿔도 옛 목소리가 그대로 재생된다."""
    text = "밤이 되었습니다."
    a = _persona(voice_name="voice-a")
    b = _persona(voice_name="voice-b")
    assert _make_cache_key(text, a.voice_for()) != _make_cache_key(text, b.voice_for())


def test_엔진이_다르면_캐시_키가_다르다() -> None:
    """엔진을 갈아끼웠는데 옛 엔진이 만든 파일이 hit되면 목소리가 안 바뀐다."""
    text = "밤이 되었습니다."
    same_voice = _persona(voice_name="v1")
    other_engine = _persona(voice_name="v1", provider="other")
    assert _make_cache_key(text, same_voice.voice_for()) != _make_cache_key(
        text, other_engine.voice_for()
    )


def test_설정된_보이스는_서로_달라야_한다() -> None:
    """두 페르소나가 같은 voice_id를 쓰면 목소리로 구분이 안 되고, 말투가
    같은 구간에서는 캐시까지 겹친다."""
    configured = [p.voice_name for p in PERSONAS.values() if p.voice_name]
    assert len(configured) == len(set(configured))


def test_같은_페르소나의_다른_말투도_캐시_키가_다르다() -> None:
    """말투가 다르면 합성 결과도 다르므로 prewarm이 말투별로 필요하다."""
    p = _persona()
    text = "잠깐만요!"
    assert _make_cache_key(text, p.voice_for()) != _make_cache_key(
        text, p.voice_for(AgentRole.REFEREE.value)
    )


def test_deliveries가_prewarm_대상을_빠짐없이_알려준다() -> None:
    p = _persona()
    roles = {role for role, _ in p.deliveries()}
    assert roles == {"", AgentRole.REFEREE.value, DELIVERY_EXCITED}


# ── 4. 페르소나 목록 ──────────────────────────────────────────────────────────


def test_기본_페르소나가_존재한다() -> None:
    assert DEFAULT_PERSONA_ID in PERSONAS
    assert get_persona().id == DEFAULT_PERSONA_ID


def test_없는_id는_기본값으로_떨어진다() -> None:
    """오타 하나로 진행이 멈추면 안 된다."""
    assert get_persona("없는페르소나").id == DEFAULT_PERSONA_ID
    assert get_persona(None).id == DEFAULT_PERSONA_ID


@pytest.mark.parametrize("persona_id", sorted(PERSONAS))
def test_모든_페르소나가_말투_지시를_갖는다(persona_id: str) -> None:
    """style_prompt가 비면 LLM이 말투를 바꿀 근거가 없어 원문이 그대로 나간다."""
    persona = PERSONAS[persona_id]
    assert persona.style_prompt
    assert persona.display_name
    assert persona.provider


@pytest.mark.parametrize("persona_id", sorted(PERSONAS))
def test_말투_지시가_TTS_안전_규칙을_담는다(persona_id: str) -> None:
    """LLM 출력이 곧 TTS 입력이다. 마크다운이나 이모지가 섞이면 그대로 읽힌다."""
    prompt = PERSONAS[persona_id].style_prompt
    assert "이모지" in prompt
    assert "숫자" in prompt  # 원문의 숫자를 바꾸지 말라는 규칙


# ── 5. 전환은 목소리·말투·화면을 함께 바꾼다 ─────────────────────────────────
# 셋이 따로 놀면 목소리만 바뀌고 말투는 그대로이거나, 음성과 자막이 다른 말을
# 하게 된다. 전환은 반드시 apply_persona를 거친다.


@pytest.fixture(autouse=True)
def _reset_lines():
    yield
    lines.use_persona(None)


@pytest.mark.anyio
async def test_전환하면_목소리와_말투가_함께_바뀐다(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lines, "PERSONA_LINES_DIR", tmp_path)
    target = sorted(PERSONAS)[0]
    (tmp_path / f"{target}.json").write_text(
        json.dumps({"werewolf.night_start": "밤이다. 눈 감아라."}, ensure_ascii=False),
        encoding="utf-8",
    )
    mgr = AudioManager(TTSEngine())

    report = await apply_persona(target, mgr, prewarm=False)

    assert mgr.persona.id == target                      # 목소리
    assert lines.get("werewolf.night_start") == "밤이다. 눈 감아라."   # 말투
    assert report.applied == 1


@pytest.mark.anyio
async def test_전환하면_화면_문구도_밀어준다() -> None:
    """자막이 옛 문장으로 남으면 음성과 다른 말을 한다."""
    sent: list[object] = []

    async def broadcast(msg: object) -> None:
        sent.append(msg)

    await apply_persona(sorted(PERSONAS)[0], None, broadcast, prewarm=False)

    assert len(sent) == 1
    msg = sent[0]
    assert msg.msg_type == "lines_catalog"  # type: ignore[attr-defined]
    assert msg.payload["lines"]  # type: ignore[attr-defined]


@pytest.mark.anyio
async def test_카탈로그를_hello로_보내지_않는다() -> None:
    """프론트는 hello를 새 접속 신호로 쓴다 — 다시 보내면 게임이 재시작된다."""
    assert catalog_message().msg_type != "hello"


@pytest.mark.anyio
async def test_화면_갱신에_실패해도_음성은_바뀐다() -> None:
    async def broken(msg: object) -> None:
        raise RuntimeError("소켓 끊김")

    mgr = AudioManager(TTSEngine())
    report = await apply_persona(sorted(PERSONAS)[0], mgr, broken, prewarm=False)

    assert mgr.persona.id == sorted(PERSONAS)[0]
    assert report.persona.id == sorted(PERSONAS)[0]


@pytest.mark.anyio
async def test_없는_페르소나로_전환하면_기본값() -> None:
    report = await apply_persona("없는거", None, prewarm=False)
    assert report.persona.id == DEFAULT_PERSONA_ID
