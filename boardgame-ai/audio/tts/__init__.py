"""TTS 엔진 어댑터.

엔진마다 잘하는 것이 다르다. 캐릭터가 강한 목소리는 그 목소리를 가진 엔진에서만
나오고, 무난한 안내는 어디서든 된다. 그래서 페르소나가 엔진을 고른다.

여기 있는 것은 "텍스트 → 오디오 바이트" 어댑터뿐이다. 캐시·동시성 제한·
벤치마크 훅은 audio/tts_engine.py가 엔진과 무관하게 처리한다.
"""

from __future__ import annotations

from audio.tts.base import DEFAULT_PROVIDER, TTSProvider, get_provider

__all__ = ["DEFAULT_PROVIDER", "TTSProvider", "get_provider"]
