"""TTS 엔진 어댑터 계약.

구현체는 "텍스트 + 보이스 설정 → 오디오 바이트" 하나만 책임진다.
캐시도, 재시도도, 동시성 제한도 여기서 하지 않는다 — 그건 엔진이 무엇이든
같은 방식이라 audio/tts_engine.py가 한 번만 구현한다.

지금은 Typecast 하나뿐이다. 어댑터 계층을 남겨두는 것은 엔진을 갈아끼울 때
tts_engine.py를 다시 뜯지 않기 위해서다 — 구글에서 옮겨올 때 그게 없어서
합성 코드가 캐시 로직과 엉켜 있었다.
"""

from __future__ import annotations

import logging
from typing import Protocol

from core.persona import VoiceConfig

logger = logging.getLogger(__name__)

DEFAULT_PROVIDER = "typecast"


class TTSProvider(Protocol):
    """엔진 어댑터가 지켜야 할 것."""

    name: str

    def is_available(self) -> bool:
        """지금 합성할 수 있는가. 키가 없거나 의존성이 없으면 False."""
        ...

    def unavailable_reason(self) -> str:
        """왜 못 쓰는지. 로그에 남겨 원인을 찾을 수 있게 한다."""
        ...

    @property
    def audio_ext(self) -> str:
        """캐시 파일 확장자. 엔진마다 내보내는 포맷이 다르다."""
        ...

    def synthesize_sync(self, text: str, voice: VoiceConfig) -> bytes:
        """동기 합성. 상위에서 스레드로 감싸 비동기화한다."""
        ...


def get_provider(name: str | None = None) -> TTSProvider:
    """이름으로 어댑터를 만든다. 모르는 이름이면 기본 엔진.

    엔진 이름 오타로 서버가 죽지 않게 한다 — 음성이 안 나오는 것과 서버가
    안 뜨는 것은 무게가 다르다.
    """
    key = (name or DEFAULT_PROVIDER).lower()
    if key != DEFAULT_PROVIDER:
        logger.warning("알 수 없는 TTS 엔진 %r — %s로 대체합니다", name, DEFAULT_PROVIDER)
    from audio.tts.typecast import TypecastProvider

    return TypecastProvider()
