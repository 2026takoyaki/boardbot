"""WebSocket 메시지 공통 봉투."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from core.audio import SFXRequest, TTSRequest
from core.constants import MsgType
from core.events import FusionContext, GameEvent


@dataclass
class WSMessage:
    msg_type: str
    payload: dict[str, Any]
    state_version: int = 0
    msg_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:12]}")
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "msg_type": self.msg_type,
            "payload": self.payload,
            "state_version": self.state_version,
            "msg_id": self.msg_id,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> WSMessage:
        return cls(
            msg_type=d["msg_type"],
            payload=dict(d["payload"]),
            state_version=int(d.get("state_version", 0)),
            msg_id=d["msg_id"],
            timestamp=float(d["timestamp"]),
        )

    @classmethod
    def make_game_event(cls, event: GameEvent, state_version: int = 0) -> WSMessage:
        return cls(
            msg_type=MsgType.GAME_EVENT.value,
            payload=event.to_dict(),
            state_version=state_version,
            msg_id=f"evt_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_fusion_context(cls, context: FusionContext, state_version: int = 0) -> WSMessage:
        return cls(
            msg_type=MsgType.FUSION_CONTEXT.value,
            payload=context.to_dict(),
            state_version=state_version,
            msg_id=f"ctx_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_tts_play(cls, request: TTSRequest, state_version: int = 0) -> WSMessage:
        return cls(
            msg_type=MsgType.TTS_PLAY.value,
            payload=request.to_dict(),
            state_version=state_version,
            msg_id=f"tts_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_tts_interrupt(
        cls, playback_id: str | None = None, state_version: int = 0
    ) -> WSMessage:
        return cls(
            msg_type=MsgType.TTS_INTERRUPT.value,
            payload={"playback_id": playback_id},
            state_version=state_version,
            msg_id=f"int_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_sfx_play(cls, request: SFXRequest, state_version: int = 0) -> WSMessage:
        return cls(
            msg_type=MsgType.SFX_PLAY.value,
            payload=request.to_dict(),
            state_version=state_version,
            msg_id=f"sfx_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_bgm_play(
        cls,
        name: str,
        audio_url: str,
        loop: bool = True,
        gain_db: float = -6.0,
        fade_ms: int = 500,
        state_version: int = 0,
    ) -> WSMessage:
        return cls(
            msg_type=MsgType.BGM_PLAY.value,
            payload={
                "name": name,
                "audio_url": audio_url,
                "loop": loop,
                "gain_db": gain_db,
                "fade_ms": fade_ms,
            },
            state_version=state_version,
            msg_id=f"bgm_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_bgm_duck(
        cls,
        on: bool,
        attenuation_db: float = -12.0,
        ramp_ms: int = 150,
        state_version: int = 0,
    ) -> WSMessage:
        return cls(
            msg_type=MsgType.BGM_DUCK.value,
            payload={"on": on, "attenuation_db": attenuation_db, "ramp_ms": ramp_ms},
            state_version=state_version,
            msg_id=f"duck_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_cue(
        cls,
        cue: str,
        payload: dict[str, Any] | None = None,
        state_version: int = 0,
    ) -> WSMessage:
        """순간 연출 큐. 모달·조명·TTS를 하나의 메시지로 몬다.

        state_update가 "지금 어떤 상태인가"를 알린다면 cue는 "방금 무슨 일이
        일어났는가"를 알린다. 세 채널이 payload의 duration_ms를 공유하므로
        연출 타이밍이 어긋나지 않는다.

        조명 Cue는 재생이 끝나면 반드시 현재 Scene으로 복귀한다. 요트에서는
        이 복귀가 주사위 인식의 전제 조건이므로 연출 규칙이 아니라 요구사항이다.
        """
        return cls(
            msg_type=MsgType.CUE.value,
            # cue를 뒤에 둔다. 호출자가 payload에 실수로 "cue"를 넣어도 인자가
            # 이긴다 — 이 키는 조명·모달이 무엇을 재생할지 고르는 라우팅 키라서
            # 조용히 덮어써지면 엉뚱한 연출이 나가거나 아무것도 안 나간다.
            payload={**(payload or {}), "cue": cue},
            state_version=state_version,
            msg_id=f"cue_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_hello(cls, info: dict[str, Any] | None = None) -> WSMessage:
        return cls(
            msg_type=MsgType.HELLO.value,
            payload=info or {},
            msg_id=f"hello_{uuid.uuid4().hex[:12]}",
        )

    @classmethod
    def make_error(cls, code: str, message: str, state_version: int = 0) -> WSMessage:
        return cls(
            msg_type=MsgType.ERROR.value,
            payload={"code": code, "message": message},
            state_version=state_version,
            msg_id=f"err_{uuid.uuid4().hex[:12]}",
        )
