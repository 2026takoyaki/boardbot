"""페르소나 — 시스템이 사용자에게 보이는 하나의 인격.

**목소리는 에이전트가 아니라 페르소나가 소유한다.**

멀티에이전트(규칙·템포·진행·전략)는 구조상의 분업이지, 사용자가 알아야 할
것이 아니다. 사용자에게는 한 명이 진행하는 것으로 들려야 하고, 에이전트는 그
한 명 안에서 **누가 언제 말할지**(우선순위·인터럽트)를 정할 뿐이다.

에이전트마다 목소리를 다르게 주면 네 사람이 번갈아 떠드는 것처럼 들린다.
대신 같은 목소리의 **다른 말투**로 구분한다 — 실제 진행자도 반칙을 잡을 때
목소리를 바꾸지 않고 말투를 바꾼다.

    미아
     ├ 기본    rate 1.10        진행
     ├ 심판    rate 0.95        "잠깐만요!"   ← 또박또박 느리게
     └ 흥분    rate 1.15        "요트!!!"

pitch 시프트는 되도록 쓰지 않는다. 포먼트가 틀어져 "기계 같은" 소리의 원인이
되고, 상위 보이스 계열은 pitch를 아예 지원하지 않는 경우가 있다. 말투 차이는
speaking_rate와 문장 자체로 내는 편이 안전하다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# 말투를 고를 때 쓰는 키. 대부분 AgentRole 값과 같지만, EXCITED는 에이전트가
# 아니라 순간의 텐션이라 따로 둔다.
DELIVERY_EXCITED = "excited"


@dataclass(frozen=True)
class VoiceConfig:
    """TTS 합성 파라미터. 캐시 키가 이 값들로 만들어진다."""

    name: str  # ex: "ko-KR-Neural2-C"
    language_code: str = "ko-KR"
    speaking_rate: float = 1.0
    pitch: float = 0.0


@dataclass(frozen=True)
class Delivery:
    """같은 사람의 다른 말투. 목소리(voice name)는 바꾸지 않는다."""

    speaking_rate: float = 1.0
    pitch: float = 0.0


@dataclass(frozen=True)
class Persona:
    """진행자 한 명. 목소리 하나 + 상황별 말투 + LLM 말투 지시."""

    id: str
    display_name: str
    voice_name: str
    language_code: str = "ko-KR"
    # 기본 말투. 대부분의 발화가 이걸 쓴다.
    base: Delivery = field(default_factory=Delivery)
    # 상황별 말투. 키는 AgentRole 값 또는 DELIVERY_EXCITED.
    # 없는 키는 base로 떨어지므로, 다르게 할 것만 적으면 된다.
    by_role: dict[str, Delivery] = field(default_factory=dict)
    # LLM이 고정 멘트를 이 페르소나 말투로 바꿀 때 주입할 지시.
    # 말투만 규정하고 게임 지식은 넣지 않는다 — 그래야 게임마다 재사용된다.
    style_prompt: str = ""

    def voice_for(self, role: str | None = None) -> VoiceConfig:
        """해당 상황에서 쓸 합성 파라미터."""
        delivery = self.by_role.get(role or "", self.base)
        return VoiceConfig(
            name=self.voice_name,
            language_code=self.language_code,
            speaking_rate=delivery.speaking_rate,
            pitch=delivery.pitch,
        )

    def deliveries(self) -> list[tuple[str, VoiceConfig]]:
        """이 페르소나가 실제로 내는 모든 (상황, 파라미터) 조합.

        캐시 키가 파라미터별로 갈리므로 prewarm이 이 목록을 알아야 한다.
        하나라도 빠지면 그 말투의 첫 발화에 합성 지연이 붙는다.
        """
        out = [("", self.voice_for())]
        out.extend((role, self.voice_for(role)) for role in self.by_role)
        return out
