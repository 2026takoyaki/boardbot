"""공유 상수 정의. 게임을 모름.

게임별 Phase와 EventType은 core가 아닌 각 게임 팀이 정의한다:
    - 요트 Phase/Event  → games/yacht/phases.py (FSM 담당: 강병진)
    - 늑대 Phase/Event → games/werewolf/phases.py (FSM 담당: 유형승)
    - 요트 비전 이벤트 데이터 스키마 → vision/yacht/... (비전 담당: 김성민)
    - 늑대 비전 이벤트 데이터 스키마 → vision/werewolf/... (비전 담당: 양승경)

각 모듈은 core의 CommonEventType + 자기 게임 전용 EventType을 합쳐서
실제 EventType 집합을 사용한다. FusionContext.fsm_state와 expected_events는
그냥 문자열로 받아 처리하므로 core는 특정 게임을 import하지 않는다.
"""

from enum import StrEnum


class MsgType(StrEnum):
    GAME_EVENT = "game_event"
    FUSION_CONTEXT = "fusion_context"
    STATE_UPDATE = "state_update"
    CUE = "cue"
    INPUT = "input"
    AGENT_MESSAGE = "agent_message"
    TTS_PLAY = "tts_play"
    TTS_INTERRUPT = "tts_interrupt"
    SFX_PLAY = "sfx_play"
    BGM_PLAY = "bgm_play"
    BGM_DUCK = "bgm_duck"
    GAME_RESULT = "game_result"
    HELLO = "hello"
    # 페르소나가 바뀌어 화면 문구가 통째로 달라졌음을 알린다. hello로 다시
    # 보내면 프론트가 새 접속으로 착각해 게임을 다시 시작한다.
    LINES_CATALOG = "lines_catalog"
    ERROR = "error"


class CommonPhase(StrEnum):
    """코어 공통 phase. 게임별 Phase는 각 게임 팀 영역에서 정의."""

    PLAYER_SETUP = "player_setup"
    SEAT_REGISTER = "seat_register"  # 양손 동시 V+OK 등록 (단일 phase)
    SEAT_REGISTER_RIGHT = "seat_register_right"  # 하위 호환 유지
    SEAT_REGISTER_LEFT = "seat_register_left"  # 하위 호환 유지
    GAME_SELECT = "game_select"


class CommonEventType(StrEnum):
    """게임 불문 공통 이벤트.

    데이터 스키마:
        SEAT_HAND_REGISTERED: {"hand": "Right"|"Left", "wrist": [x,y],
                               "gesture": "v_sign"|"ok_sign"}
        SEAT_REGISTERED:      {"seat_zone": {...}}
        GESTURE_CONFIRMED:    {"gesture": "..."}
        RULE_VIOLATION:       {"violation_type": "...", "detail": "..."}
        VISION_ERROR:         {"error_code": "...", "message": "..."}
    """

    SEAT_HAND_REGISTERED = "seat_hand_registered"
    SEAT_RIGHT_REGISTERED = "seat_right_registered"  # 오른손 V사인 stab 통과 (중간 단계)
    SEAT_REGISTERED = "seat_registered"
    GESTURE_CONFIRMED = "gesture_confirmed"
    RULE_VIOLATION = "rule_violation"
    VISION_ERROR = "vision_error"


class AgentRole(StrEnum):
    REFEREE = "referee"
    TEMPO = "tempo"
    NARRATOR = "narrator"
    STRATEGY = "strategy"


class InputType(StrEnum):
    """UI → FSM 공통 입력. 게임별 input은 각 게임 팀이 자기 모듈에서 추가 정의."""

    # 플레이어 설정
    PLAYER_ADD = "player_add"
    PLAYER_EDIT = "player_edit"
    PLAYER_REMOVE = "player_remove"
    PLAYER_SETUP_DONE = "player_setup_done"
    # 게임 선택
    SELECT_GAME = "select_game"
    # 종료 3선택지
    CHANGE_PLAYERS = "change_players"
    CHANGE_GAME = "change_game"
    RESTART = "restart"
    # 좌석 폴백
    MANUAL_SEAT_FALLBACK = "manual_seat_fallback"
    # 오디오 재생 ack (frontend → backend)
    AUDIO_ACK = "audio_ack"


DEFAULT_PARAMS: dict[str, float | int] = {
    "motion_threshold_norm": 0.002,
    "motion_start_frames": 3,
    "stabilization_frames": 30,
    "gesture_stabilization_frames": 5,
    "handedness_confirm_frames": 5,
    "wrist_distance_min_norm": 0.05,
    "wrist_distance_max_norm": 0.30,
    "pointing_stabilization_frames": 10,
    "confidence_threshold": 0.6,
}
