"""한밤의 늑대인간 게임 전용 Phase·역할·이벤트·입력 타입."""

from __future__ import annotations

from enum import StrEnum


class WerewolfRole(StrEnum):
    WEREWOLF = "werewolf"
    VILLAGER = "villager"
    SEER = "seer"                  # 예언자
    ROBBER = "robber"              # 도둑
    TROUBLEMAKER = "troublemaker"  # 말썽꾼
    DRUNK = "drunk"                # 술꾼
    INSOMNIAC = "insomniac"        # 불면증환자
    HUNTER = "hunter"              # 사냥꾼
    TANNER = "tanner"              # 무두장이
    DOPPELGANGER = "doppelganger"  # 도플갱어
    MINION = "minion"              # 하수인
    MASON = "mason"                # 프리메이슨


# 늑대 팀에 속하는 역할 집합
WEREWOLF_TEAM: frozenset[str] = frozenset({
    WerewolfRole.WEREWOLF.value,
    WerewolfRole.MINION.value,
})

# 밤에 행동 순서가 있는 역할 (원나잇 늑대인간 표준 순서)
NIGHT_ORDER: list[str] = [
    WerewolfRole.DOPPELGANGER.value,
    WerewolfRole.WEREWOLF.value,
    WerewolfRole.MINION.value,
    WerewolfRole.MASON.value,
    WerewolfRole.SEER.value,
    WerewolfRole.ROBBER.value,
    WerewolfRole.TROUBLEMAKER.value,
    WerewolfRole.DRUNK.value,
    WerewolfRole.INSOMNIAC.value,
]


class WerewolfPhase(StrEnum):
    NIGHT_START = "night_start"
    NIGHT_DOPPELGANGER = "night_doppelganger"
    NIGHT_WEREWOLF = "night_werewolf"
    NIGHT_MINION = "night_minion"
    NIGHT_MASON = "night_mason"
    NIGHT_SEER = "night_seer"
    NIGHT_ROBBER = "night_robber"
    NIGHT_TROUBLEMAKER = "night_troublemaker"
    NIGHT_DRUNK = "night_drunk"
    NIGHT_INSOMNIAC = "night_insomniac"
    DAY_DISCUSSION = "day_discussion"    # 300초 타이머
    VOTE_COUNTDOWN = "vote_countdown"
    VOTE = "vote"
    RESULT = "result"


class WerewolfEventType(StrEnum):
    """비전팀이 발생시키는 늑대인간 전용 이벤트.

    카드 인식 이벤트(ROLE_DETECTED·CARD_PEEK·CARD_SWAP 등)는 인식률 문제로 제거됐다.
    시스템은 플레이어의 역할을 알지 못하며, 야간 진행은 공용 GESTURE_CONFIRMED(OK 사인)로
    처리한다.

    data 스키마:
        VOTE_POINT: {"target_id": str}
    """

    VOTE_POINT = "werewolf_vote_point"        # 투표 포인팅 감지


class WerewolfInputType(StrEnum):
    """UI → FSM 늑대인간 전용 입력.

    data 스키마:
        VOTE_PLAYER:          {"target_id": str}
        VOTE_RESULT_CONFIRM:  {}  — 투표 결과 확인 화면에서 최종 확정
        VOTE_COUNTDOWN_START: {}  — 안내 TTS 종료 후 5→0 카운트다운 시작
    """

    ADD_30_SEC = "add_30_sec"
    START_NOW = "start_now"
    VOTE_PLAYER = "werewolf_vote_player"
    VOTE_RESULT_CONFIRM = "werewolf_vote_result_confirm"
    VOTE_COUNTDOWN_START = "werewolf_vote_countdown_start"


# 야간 페이즈 순서 (NIGHT_ORDER 역할 문자열과 대응)
NIGHT_PHASES: list[WerewolfPhase] = [
    WerewolfPhase.NIGHT_DOPPELGANGER,
    WerewolfPhase.NIGHT_WEREWOLF,
    WerewolfPhase.NIGHT_MINION,
    WerewolfPhase.NIGHT_MASON,
    WerewolfPhase.NIGHT_SEER,
    WerewolfPhase.NIGHT_ROBBER,
    WerewolfPhase.NIGHT_TROUBLEMAKER,
    WerewolfPhase.NIGHT_DRUNK,
    WerewolfPhase.NIGHT_INSOMNIAC,
]

# 야간 페이즈 → 해당 역할 매핑
PHASE_TO_ROLE: dict[WerewolfPhase, WerewolfRole] = {
    WerewolfPhase.NIGHT_DOPPELGANGER: WerewolfRole.DOPPELGANGER,
    WerewolfPhase.NIGHT_WEREWOLF: WerewolfRole.WEREWOLF,
    WerewolfPhase.NIGHT_MINION: WerewolfRole.MINION,
    WerewolfPhase.NIGHT_MASON: WerewolfRole.MASON,
    WerewolfPhase.NIGHT_SEER: WerewolfRole.SEER,
    WerewolfPhase.NIGHT_ROBBER: WerewolfRole.ROBBER,
    WerewolfPhase.NIGHT_TROUBLEMAKER: WerewolfRole.TROUBLEMAKER,
    WerewolfPhase.NIGHT_DRUNK: WerewolfRole.DRUNK,
    WerewolfPhase.NIGHT_INSOMNIAC: WerewolfRole.INSOMNIAC,
}

# passive 야간 페이즈: 비전 이벤트 없이 프론트가 start_now 보낼 때까지 대기
PASSIVE_NIGHT_PHASES: frozenset[WerewolfPhase] = frozenset({
    WerewolfPhase.NIGHT_START,
    WerewolfPhase.NIGHT_WEREWOLF,
    WerewolfPhase.NIGHT_MINION,
    WerewolfPhase.NIGHT_MASON,
})

# 튜토리얼 모드에서 등록 여부와 무관하게 항상 진행하는 늑대팀 패시브 안내 페이즈
TUTORIAL_ALWAYS_PHASES: frozenset[WerewolfPhase] = frozenset({
    WerewolfPhase.NIGHT_WEREWOLF,
    WerewolfPhase.NIGHT_MINION,
    WerewolfPhase.NIGHT_MASON,
})
