"""오디오 카탈로그: 멘트 템플릿, SFX 레지스트리, 보이스 설정.

세 계층의 캐시 구분:
- STATIC_LINES: 플레이어 이름 없는 완전 고정 멘트. 부팅 시 prewarm.
- SESSION_TEMPLATES: 플레이어 이름 슬롯이 있는 반고정 멘트. 좌석 등록 직후 prewarm.
- 그 외(dynamic): on-demand 합성. 예: 주사위 값/점수 포함 멘트.

resolve_static(text)으로 백엔드 텍스트가 어느 캐시 계층에 있는지 판단한다.
"""

from __future__ import annotations

import re
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
DEFAULT_VOICE = VoiceConfig(name="ko-KR-Neural2-A")


# ── STATIC: 플레이어 이름 없는 완전 고정 멘트 ──────────────────────────────────
# 부팅 시 1회 prewarm. tts_cache/static/에 저장.
# 각 게임 담당자가 자기 게임 멘트를 여기 추가하면 자동으로 prewarm된다.
# 예: STATIC_LINES = ["게임이 종료되었습니다.", "잠시만 기다려주세요."]

STATIC_LINES: list[str] = [
    # ── 웨어울프 (일반 모드) ───────────────────────────────────────────────────────
    "밤이 되었습니다. 모두 눈을 감아주세요.",
    "도플갱어는 깨어나세요. 다른 플레이어 1명의 카드를 확인하세요. 그 역할이 됩니다.",
    "늑대인간은 깨어나세요. 서로를 확인하고 다시 눈을 감으세요.",
    "하수인은 깨어나세요. 늑대인간들은 엄지를 들어올려 자신을 알려주세요.",
    "프리메이슨은 깨어나세요. 서로를 확인하고 다시 눈을 감으세요.",
    # ── 웨어울프 (일반 모드 — 액티브 역할) ───────────────────────────────────────
    "예언자는 깨어나세요. 다른 플레이어 1명 또는 중앙 카드 2장을 확인할 수 있습니다.",
    "주정뱅이는 깨어나세요. 중앙 카드 1장을 가져와 자신의 카드와 교환하세요. 새 카드는 볼 수 없습니다.",
    "불면증환자는 깨어나세요. 자신의 카드를 확인하세요.",
    # ── 웨어울프 (튜토리얼 모드 — "차례입니다" + 플레이어 행동 안내) ──────────────
    "밤이 되었습니다. 튜토리얼 모드에서는 눈을 감지 않고 진행합니다. 차례가 되면 해당 역할 플레이어가 행동을 수행하면 됩니다.",
    "도플갱어 차례입니다. 도플갱어 플레이어는 다른 플레이어 1명의 카드를 확인하고 그 역할을 따라 행동합니다.",
    "늑대인간 차례입니다. 늑대인간 플레이어끼리 손을 들어 서로가 누구인지 확인합니다.",
    "하수인 차례입니다. 하수인 플레이어는 늑대인간이 누구인지 확인합니다.",
    "프리메이슨 차례입니다. 프리메이슨 플레이어끼리 서로가 누구인지 확인합니다.",
    "예언자 차례입니다. 예언자 플레이어는 다른 플레이어 1명 또는 중앙 카드 2장을 확인합니다.",
    "강도 차례입니다. 강도 플레이어는 다른 플레이어 1명의 카드를 자신의 카드와 바꾼 뒤, 새 카드를 확인합니다.",
    "말썽쟁이 차례입니다. 말썽쟁이 플레이어는 자신을 제외한 두 플레이어의 카드를 서로 바꿉니다.",
    "주정뱅이 차례입니다. 주정뱅이 플레이어는 중앙 카드 1장과 자신의 카드를 바꿉니다. 새 카드는 확인하지 않습니다.",
    "불면증환자 차례입니다. 불면증환자 플레이어는 마지막으로 자신의 카드를 확인합니다.",
    "모두 눈을 뜨세요! 토론을 시작합니다.",
    # 아침 안내는 화면이 제목/부제로 나눠 보여줘서 두 줄로 쪼개져 있다
    # (agents/tools/lines.py의 werewolf.morning / morning_open_eyes).
    "아침이 밝았습니다.",
    "모두 눈을 뜨세요.",
    "자, 지금부터 토론을 시작합니다.",
    "투표를 시작합니다. 제거할 플레이어를 지목하세요.",
    "마을 팀이 승리했습니다!",
    "늑대인간 팀이 승리했습니다!",
    "무두장이가 승리했습니다!",
]

# 족보/하이라이트 외침. EXCITED_VOICE로 별도 prewarm.
# 캐치프레이즈, 점수 발표 시 강조 외침 등.
# 예: EXCITED_LINES = ["야추!", "포 카드!"]

EXCITED_LINES: list[str] = []


# ── SESSION: 플레이어 이름 슬롯 멘트 템플릿 ────────────────────────────────────
# 좌석 등록 완료 후 prewarm. 각 플레이어 이름으로 변형해 tts_cache/session/<session_id>/에 저장.
# {player} 슬롯만 지원 (단일 슬롯). 다중 플레이어가 등장하는 멘트(점수 발표 등)는 dynamic으로.
# 예: SESSION_TEMPLATES = ["{player}님 차례입니다.", "{player}님, 다시 굴려주세요."]

SESSION_TEMPLATES: list[str] = []


def format_session_line(template: str, player_name: str) -> str:
    """SESSION_TEMPLATES의 {player} 슬롯에 이름을 채워 실제 멘트로 변환."""
    return template.format(player=player_name)


def expand_session_lines(player_names: list[str]) -> list[tuple[str, str]]:
    """각 플레이어 × 각 템플릿 조합으로 (template, formatted_text) 리스트 반환.

    AudioManager가 prewarm 시 호출. template은 캐시 키 일관성 위해 보관.
    """
    return [
        (template, format_session_line(template, name))
        for name in player_names
        for template in SESSION_TEMPLATES
    ]


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


# ── 텍스트 → 캐시 계층 분류 ────────────────────────────────────────────────────


def classify_text(text: str) -> str:
    """text가 어느 캐시 계층에 속하는지 판단.

    Returns: "static" | "session" | "dynamic"
    """
    if text in STATIC_LINES:
        return "static"

    # SESSION_TEMPLATES와 정확히 매칭되는 패턴 탐색
    for template in SESSION_TEMPLATES:
        pattern = re.escape(template).replace(r"\{player\}", r"[가-힣A-Za-z0-9]{1,10}")
        if re.fullmatch(pattern, text):
            return "session"

    return "dynamic"


def session_template_for(text: str) -> str | None:
    """주어진 text가 어떤 SESSION_TEMPLATE을 instantiate한 것인지 역추적.

    캐시 키 안정화를 위해 사용. 매칭 실패 시 None.
    """
    for template in SESSION_TEMPLATES:
        pattern = re.escape(template).replace(r"\{player\}", r"([가-힣A-Za-z0-9]{1,10})")
        if re.fullmatch(pattern, text):
            return template
    return None
