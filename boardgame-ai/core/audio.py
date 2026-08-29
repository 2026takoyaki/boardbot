"""TTS/오디오 메시지 타입. Phase 1부터 FSM이 TTS 재생 요청에 사용."""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum
from typing import Any


class AudioType(StrEnum):
    TTS = "tts"
    SFX = "sfx"
    BGM = "bgm"


class AudioPriority(IntEnum):
    # 지금 반드시 들려야 하는 말. 현재 재생 즉시 인터럽트(fade-out) + 큐의
    # interruptible 항목 제거. 규칙 위반 제지와, 야간 단계 마감 지시
    # ("눈을 다시 감아주세요")가 여기 온다 — 둘 다 밀리면 뜻을 잃는다.
    CRITICAL = 1
    HIGH = 2  # 템포
    NORMAL = 3  # 일반 멘트
    LOW = 4  # BGM


@dataclass
class TTSRequest:
    text: str
    audio_url: str | None = None  # 미리 캐시된 wav 경로. AudioManager가 합성 후 채움.
    audio_type: AudioType = AudioType.TTS
    priority: AudioPriority = AudioPriority.NORMAL
    agent: str = "narrator"  # AgentRole.value
    interruptible: bool = True
    playback_id: str | None = None
    sequence_id: str | None = None  # 같은 sequence는 ack 받기 전 다음 항목 대기
    seq_index: int = 0
    state_version: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "audio_url": self.audio_url,
            "audio_type": self.audio_type.value,
            "priority": self.priority.value,
            "agent": self.agent,
            "interruptible": self.interruptible,
            "playback_id": self.playback_id,
            "sequence_id": self.sequence_id,
            "seq_index": self.seq_index,
            "state_version": self.state_version,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> TTSRequest:
        return cls(
            text=d["text"],
            audio_url=d.get("audio_url"),
            audio_type=AudioType(d.get("audio_type", AudioType.TTS.value)),
            priority=AudioPriority(d.get("priority", AudioPriority.NORMAL.value)),
            agent=d.get("agent", "narrator"),
            interruptible=bool(d.get("interruptible", True)),
            playback_id=d.get("playback_id"),
            sequence_id=d.get("sequence_id"),
            seq_index=int(d.get("seq_index", 0)),
            state_version=int(d.get("state_version", 0)),
        )


@dataclass
class SFXRequest:
    name: str  # SFX_REGISTRY 키
    audio_url: str | None = None
    priority: AudioPriority = AudioPriority.NORMAL
    interruptible: bool = True
    playback_id: str | None = None
    sequence_id: str | None = None
    seq_index: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "audio_url": self.audio_url,
            "audio_type": AudioType.SFX.value,
            "priority": self.priority.value,
            "interruptible": self.interruptible,
            "playback_id": self.playback_id,
            "sequence_id": self.sequence_id,
            "seq_index": self.seq_index,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> SFXRequest:
        return cls(
            name=d["name"],
            audio_url=d.get("audio_url"),
            priority=AudioPriority(d.get("priority", AudioPriority.NORMAL.value)),
            interruptible=bool(d.get("interruptible", True)),
            playback_id=d.get("playback_id"),
            sequence_id=d.get("sequence_id"),
            seq_index=int(d.get("seq_index", 0)),
        )
