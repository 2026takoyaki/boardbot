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
# 발표용으로 미리 만들어 둔 목소리. **캐시가 아니라 자산이다** — tts_cache는
# .gitignore에 있고 지워도 다시 만들어지지만, 이쪽은 지우면 발표장에서
# 되살릴 방법이 없다(합성하려면 키와 인터넷이 필요하다). 그래서 저장소에
# 함께 들어간다. 만드는 법은 tools/generate_show_voices.py.
SHOW_DIR = ASSETS_DIR / "show"

# 캐시 계층별 디렉토리
STATIC_CACHE_DIR = TTS_CACHE_DIR / "static"
SESSION_CACHE_DIR = TTS_CACHE_DIR / "session"
DYNAMIC_CACHE_DIR = TTS_CACHE_DIR / "dynamic"

# 발표용 음원의 확장자. Typecast가 wav를 내보낸다(audio/tts/typecast.py의
# audio_ext). 엔진을 바꾸면 여기와 파일을 같이 바꿔야 한다.
SHOW_VOICE_EXT = "wav"


def show_voice_url(act_id: str) -> str:
    """브라우저가 받아갈 경로. 서버가 /show/ 로 이 디렉토리를 서빙한다."""
    return f"/show/{act_id}.{SHOW_VOICE_EXT}"


def show_voice_path(act_id: str) -> Path:
    return SHOW_DIR / f"{act_id}.{SHOW_VOICE_EXT}"


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

# 자산 파일 위치: audio/assets/sfx/<filename>. 서버가 /sfx/<filename>로 서빙.
#
# 소리는 세 갈래다. 섞이면 인식이 될 때마다 축하받는 꼴이 된다.
#   시스템 피드백 — 순수 디지털 톤. 기계가 응답하는 소리
#   요트          — 따뜻한 금색 벨. 음악적이고 감정이 실린다
#   늑대인간      — 낮은 드론. 어둡고 분위기 위주
SFX_REGISTRY: dict[str, str] = {
    # ── 시스템 피드백 (공용) ──
    "ui_click": "/sfx/ui_click.mp3",                  # 버튼 누름
    "hand_register": "/sfx/hand_register.mp3",        # 손 등록. 좌우 각각 울린다
    "dice_recognized": "/sfx/dice_recognized.mp3",    # 주사위 눈 인식 완료
    "warn": "/sfx/warn.mp3",                          # 규칙 위반 제지
    # ── 요트 ──
    # 굴림 축하. 등급은 악기를 바꾸지 않고 층을 쌓아 낸다(같은 벨이 심지).
    "hand_good": "/sfx/hand_good.mp3",                # 포카드·풀하우스·스몰
    "hand_epic": "/sfx/hand_epic.mp3",                # 라지 스트레이트
    "hand_legendary": "/sfx/hand_legendary.mp3",      # 야찌
    "score_normal": "/sfx/score_normal.mp3",          # 일반 득점
    "score_zero": "/sfx/score_zero.mp3",              # 0점 처리
    "lead_change": "/sfx/lead_change.mp3",            # 선두 역전
    "upper_bonus": "/sfx/upper_bonus.mp3",            # 상단 보너스 달성
    "game_end": "/sfx/game_end.mp3",                  # 결과 발표 징글
    # ── 늑대인간 ──
    "wolf_sound": "/sfx/wolf_sound.mp3",              # 늑대 울음. 밤 시작 분위기
    # ── 컨트롤 세션 ──
    # 진행자가 버튼으로 직접 트는 소리. 조명 큐와 짝을 이룬다(bulb/scenes.py).
    #
    # 파일이 아직 없어도 등록해 둔다. 없는 이름을 넘기면 AudioManager가 경고만
    # 찍고 아무것도 안 보내서 조명까지 같이 죽은 것처럼 보인다. 등록해 두면
    # 브라우저가 404를 조용히 무시하고 조명은 정상으로 도므로, 파일을 넣는
    # 순간 소리만 붙는다.
    "control_celebrate": "/sfx/control_celebrate.mp3",  # 축하
    "control_tease": "/sfx/control_tease.mp3",  # 약올리기
    "control_applause": "/sfx/control_applause.mp3",  # 박수
    "control_fart": "/sfx/control_fart.mp3",  # 방구
    "control_party": "/sfx/control_party.mp3",  # 파티 — 10초 안팎의 댄스 음악
}

# BGM 레지스트리. 자산 파일: audio/assets/bgm/<filename>. 서버 /bgm/<filename>.
BGM_REGISTRY: dict[str, str] = {
    "lobby_loop": "/bgm/lobby_loop.mp3",  # 로비/게임 진행 중 배경음 (loop)
    "game_outro": "/bgm/game_outro.mp3",  # 우승자 발표 후 배경음
    "yacht_walk": "/bgm/Yacht%20Theme_%20Walk%20Through%20The%20Park.mp3",
    "werewolf_night": "/bgm/werewolf_night.mp3",  # 늑대인간 밤 단계
    "werewolf_day": "/bgm/werewolf_day.mp3",      # 늑대인간 낮(토론) 단계
}
