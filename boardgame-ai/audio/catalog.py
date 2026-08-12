"""오디오 자산 경로와 SFX/BGM 레지스트리.

**멘트는 여기 없다.** 문장의 소유자는 agents/tools/lines.py이고, 페르소나에
따라 달라진다. 여기에 목록을 두면 페르소나가 문장을 바꿨을 때 그 목록이
통째로 어긋나 prewarm이 아무도 안 쓸 문장을 만들어 두게 된다.

캐시 계층(static/session/dynamic)도 문장 내용이 아니라 슬롯 유무로 정해지며,
AudioManager가 주입받은 목록으로 판정한다(set_line_catalog).
"""

from __future__ import annotations

from pathlib import Path

# VoiceConfig의 소유자는 core다. 기존 import 경로(audio.catalog)를 깨지 않도록
# 여기서 다시 내보낸다.
from core.persona import VoiceConfig

__all__ = ["VoiceConfig"]


# 프로젝트 루트(boardgame-ai/) 기준 경로
_BASE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = _BASE_DIR / "assets"
TTS_CACHE_DIR = ASSETS_DIR / "tts_cache"
SFX_DIR = ASSETS_DIR / "sfx"
BGM_DIR = ASSETS_DIR / "bgm"

# 캐시 계층별 디렉토리
STATIC_CACHE_DIR = TTS_CACHE_DIR / "static"
SESSION_CACHE_DIR = TTS_CACHE_DIR / "session"
DYNAMIC_CACHE_DIR = TTS_CACHE_DIR / "dynamic"


# 목소리는 여기가 아니라 페르소나가 소유한다(core/persona.py).
#
# 에이전트마다 목소리를 다르게 주면 네 사람이 번갈아 떠드는 것처럼 들린다.
# 사용자에게는 한 명이 진행하는 것으로 들려야 하고, 에이전트는 그 한 명 안에서
# 누가 언제 말할지(우선순위·인터럽트)만 정한다.
#
# 어떤 페르소나를 쓸지는 AudioManager가 주입받는다 — audio가 agents를 알면
# 계층이 뒤집히므로, 고르는 것은 위(backend)의 일이다.
#
# 아래는 페르소나가 아직 주입되지 않았을 때의 최소 폴백이다. 실제 운영에서는
# 항상 페르소나가 설정되므로 쓰이지 않는다.
DEFAULT_VOICE = VoiceConfig(name="")


# ── SFX 레지스트리 ─────────────────────────────────────────────────────────────
# 키 → 정적 파일 경로. frontend는 audio_url로 접근.

SFX_REGISTRY: dict[str, str] = {
    # 자산 파일 위치: audio/assets/sfx/<filename>. 서버가 /sfx/<filename>로 서빙.
    "hand_register": "/sfx/hand_register.mp3",  # 좌석 등록 완료
    "dice_roll": "/sfx/dice_roll.mp3",          # 주사위 굴림
    "score_select": "/sfx/score_select.mp3",    # 점수판 카테고리 선택
    "game_start": "/sfx/game_start.mp3",        # 게임 시작 알림
    "game_end": "/sfx/game_end.mp3",            # 결과 발표 징글
    "wolf_sound": "/sfx/wolf_sound.mp3",        # 늑대 울음. 늑대인간 밤 시작 분위기.
}

# BGM 레지스트리. 자산 파일: audio/assets/bgm/<filename>. 서버 /bgm/<filename>.
BGM_REGISTRY: dict[str, str] = {
    "lobby_loop": "/bgm/lobby_loop.mp3",  # 로비/게임 진행 중 배경음 (loop)
    "game_outro": "/bgm/game_outro.mp3",  # 우승자 발표 후 배경음
    "yacht_walk": "/bgm/Yacht%20Theme_%20Walk%20Through%20The%20Park.mp3",
    "werewolf_night": "/bgm/werewolf_night.mp3",  # 늑대인간 밤 단계
    "werewolf_day": "/bgm/werewolf_day.mp3",      # 늑대인간 낮(토론) 단계
}
