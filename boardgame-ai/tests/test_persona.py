"""페르소나 — 목소리의 소유자.

지키는 것:
1. 누가 말하든 페르소나의 목소리 하나로 나간다 (에이전트마다 다른 사람이 아님).
2. 말투는 상황에 따라 갈리되 목소리 이름은 그대로다.
3. 페르소나를 바꾸면 캐시 키가 달라진다 — prewarm이 따라와야 한다는 근거.
"""

from __future__ import annotations

import pytest

from agents.personas import DEFAULT_PERSONA_ID, PERSONAS, get_persona
from audio.manager import AudioManager
from audio.tts_engine import TTSEngine, _make_cache_key
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
    """목소리 조회가 죽으면 발화가 통째로 사라진다. 밋밋한 게 침묵보다 낫다."""
    mgr = AudioManager(TTSEngine())
    voice = mgr._voice_for(_request("아무 말", AgentRole.NARRATOR.value))
    assert voice.name


@pytest.mark.anyio
async def test_페르소나를_바꾸면_목소리가_바뀐다() -> None:
    mgr = AudioManager(TTSEngine(), get_persona("mia"))
    before = mgr._voice_for(_request("안녕", AgentRole.NARRATOR.value))
    # prewarm=False: 합성 없이 목소리만 교체 (TTS 자격증명 없이도 검증 가능)
    await mgr.set_persona(get_persona("dante"), prewarm=False)
    after = mgr._voice_for(_request("안녕", AgentRole.NARRATOR.value))

    assert before.name != after.name
    assert mgr.persona.id == "dante"


# ── 3. 캐시 정합성 ────────────────────────────────────────────────────────────


def test_페르소나가_다르면_캐시_키가_다르다() -> None:
    """같은 문장이라도 목소리가 다르면 다른 파일이어야 한다. 안 그러면 페르소나를
    바꿔도 옛 목소리가 그대로 재생된다."""
    text = "밤이 되었습니다."
    keys = {
        _make_cache_key(text, persona.voice_for()) for persona in PERSONAS.values()
    }
    assert len(keys) == len(PERSONAS)


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
    assert persona.voice_name.startswith("ko-KR-")


@pytest.mark.parametrize("persona_id", sorted(PERSONAS))
def test_말투_지시가_TTS_안전_규칙을_담는다(persona_id: str) -> None:
    """LLM 출력이 곧 TTS 입력이다. 마크다운이나 이모지가 섞이면 그대로 읽힌다."""
    prompt = PERSONAS[persona_id].style_prompt
    assert "이모지" in prompt
    assert "숫자" in prompt  # 원문의 숫자를 바꾸지 말라는 규칙
