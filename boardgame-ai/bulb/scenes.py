"""Scene · Cue 정의.

조명 연출에는 성격이 다른 두 종류가 있다.

    Scene — 페이즈가 유지되는 동안의 바탕 조명. 수명이 페이즈와 같다.
    Cue   — 순간적으로 터지고 Scene으로 돌아온다. 0.5~3초.

Cue의 계약: **반드시 Scene으로 복귀하며 끝난다.** 이 규칙이 있어야 조명이
이상한 상태로 멈춰 요트 주사위 인식을 망치는 사고를 구조적으로 막을 수 있다.

게임별 매핑 테이블은 이 모듈이 아니라 후속 작업에서 채운다. 여기서는 타입과
어디서나 안전한 기본값만 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from bulb.driver.base import RGB
from games.werewolf.ontology import WerewolfPhase
from games.yacht.state import YachtPhase

NEUTRAL_WHITE: RGB = (255, 255, 255)


@dataclass(frozen=True)
class Scene:
    """페이즈가 유지되는 동안의 바탕 조명."""

    name: str
    color: RGB
    brightness: int
    transition_ms: int = 1200

    @property
    def is_blackout(self) -> bool:
        return self.brightness <= 0


@dataclass(frozen=True)
class Cue:
    """터지고 Scene으로 돌아오는 순간 연출.

    rise → hold → fall 세 구간으로 쪼갠 이유는 복귀 페이드(fall)를 길이 계산에
    반드시 포함시키기 위해서다. 복귀가 끝나는 시점이 곧 "다음 굴림을 인식해도
    안전한 시점"이라, 이 값이 모달 지속시간과 맞물린다.
    """

    name: str
    color: RGB
    brightness: int
    rise_ms: int
    hold_ms: int
    fall_ms: int

    @property
    def total_ms(self) -> int:
        """복귀 페이드까지 포함한 전체 길이."""
        return self.rise_ms + self.hold_ms + self.fall_ms

    def fits_within(self, duration_ms: int) -> bool:
        """모달이 닫히기 전에 조명이 Scene으로 돌아와 있는가.

        설계문서 §2.4의 불변식: 모달 duration >= Cue 전체 길이.
        요트에서 이걸 어기면 모달이 사라진 뒤에도 조명이 아직 색을 물고 있고,
        그 상태로 다음 굴림이 들어와 인식이 깨진다.
        """
        return self.total_ms <= duration_ms


# 어디서 쓰든 안전한 바탕. 인식이 필요한 구간(요트 전 구간, 로비 좌석 등록)의
# 기본값이자, 매핑에 없는 페이즈를 만났을 때의 폴백이다.
NEUTRAL_SCENE = Scene(
    name="neutral",
    color=NEUTRAL_WHITE,
    brightness=100,
    transition_ms=800,
)

# 완전한 어둠. 늑대인간 "밤이 되었습니다" 구간처럼 비전이 유휴일 때만 쓴다.
# 요트에서 이 Scene이 요청되면 밝기 하한에 걸려 자동으로 걷어내진다.
BLACKOUT_SCENE = Scene(
    name="blackout",
    color=NEUTRAL_WHITE,
    brightness=0,
    transition_ms=2000,
)


# ── 색 팔레트 ────────────────────────────────────────────────────────────────
#
# 역할마다 다른 색을 주면 10색이 되어 산만하고 촌스럽다. 대신 **의미 단위로
# 묶는다** — 악역은 붉게, 정보는 푸르게, 교란은 앰버로. 플레이어는 색이
# 몇 개인지 세지 않고 "지금 누구 차례인가"의 성격만 읽는다.
#
# 전구 1개가 유일한 광원이라 채도를 높게 잡는다. 낮은 채도는 어두운 방에서
# 그냥 흐린 흰색으로 보인다.

VILLAIN_RED: RGB = (255, 20, 20)
VILLAIN_RED_WEAK: RGB = (200, 45, 45)
SPECIAL_PURPLE: RGB = (150, 60, 220)
VILLAGE_GREEN: RGB = (40, 200, 90)
INFO_INDIGO: RGB = (70, 90, 230)
TRICK_AMBER: RGB = (255, 150, 30)
TENSION_RED: RGB = (255, 110, 70)
DAWN_WARM: RGB = (255, 225, 190)
CELEBRATION_GOLD: RGB = (255, 200, 90)

# 요트 전용 팔레트 — 채도를 의도적으로 낮췄다.
#
# 늑대인간 색을 그대로 쓰면 안 된다. 요트는 이 전구가 곧 주사위 인식 조명이라
# 원색이 들어오면 YOLO가 학습 시점과 다른 색분포를 본다. 그래서 요트 연출은
# **색을 갈아엎지 않고 톤만 얹는다** — 백색에 가까운 틴트로 광량을 유지한 채
# 방 전체의 온도만 바꾼다. 단일 광원이라 이 정도로도 변화는 충분히 보인다.
#
# 연출의 세기는 조명이 아니라 화면 모달이 감당한다.
YACHT_SWEEP_WARM: RGB = (255, 226, 178)
YACHT_BURST_GOLD: RGB = (255, 214, 140)


def build_werewolf_scenes(night_brightness: int) -> dict[str, Scene]:
    """늑대인간 페이즈 → Scene.

    키는 games/werewolf/ontology.py 의 WerewolfPhase 값이다. 이 이름은 계약이라
    바꾸려면 조명 담당자와 합의해야 한다 (설계문서 §3.4).

    밤 밝기는 인자로 받는다. 전구 1개가 유일한 광원이라 이 값 하나가 밤의
    어둠을 전적으로 결정하고, "어둡되 최소한 보이긴 해야 한다"는 지점은
    실물로만 찾을 수 있다 (§7.2-8). 현장에서 LIGHT_NIGHT_BRIGHTNESS 로 조정한다.
    """
    night = night_brightness
    return {
        # "밤이 되었습니다" — 완전한 암전에서 시작한다. 여기서 각 역할의 색이
        # 스며들어야 장면이 산다. 밤에는 비전이 할 일이 없어 소등해도 잃을 게 없다.
        WerewolfPhase.NIGHT_START.value: BLACKOUT_SCENE,
        WerewolfPhase.NIGHT_DOPPELGANGER.value: Scene(
            "ww_doppelganger", SPECIAL_PURPLE, night, 1200
        ),
        WerewolfPhase.NIGHT_WEREWOLF.value: Scene("ww_werewolf", VILLAIN_RED, night, 1200),
        WerewolfPhase.NIGHT_MINION.value: Scene("ww_minion", VILLAIN_RED_WEAK, night, 1200),
        WerewolfPhase.NIGHT_MASON.value: Scene("ww_mason", VILLAGE_GREEN, night, 1200),
        WerewolfPhase.NIGHT_SEER.value: Scene("ww_seer", INFO_INDIGO, night, 1200),
        WerewolfPhase.NIGHT_INSOMNIAC.value: Scene("ww_insomniac", INFO_INDIGO, night, 1200),
        WerewolfPhase.NIGHT_ROBBER.value: Scene("ww_robber", TRICK_AMBER, night, 1200),
        WerewolfPhase.NIGHT_TROUBLEMAKER.value: Scene(
            "ww_troublemaker", TRICK_AMBER, night, 1200
        ),
        WerewolfPhase.NIGHT_DRUNK.value: Scene("ww_drunk", TRICK_AMBER, night, 1200),
        # ★ 이 게임의 감정적 클라이막스. 어둠에서 따뜻한 빛이 2.5초에 걸쳐
        # 차오르며 TTS가 얹힌다. 프론트 PhaseTransition의 dawn 타입
        # (duration 2500, midAt 300)과 타이밍을 맞춘다.
        WerewolfPhase.DAY_DISCUSSION.value: Scene("ww_dawn", DAWN_WARM, 100, 2500),
        WerewolfPhase.VOTE_COUNTDOWN.value: Scene("ww_countdown", TENSION_RED, 60, 2000),
        WerewolfPhase.VOTE.value: Scene("ww_vote", VILLAIN_RED, 55, 1000),
        # 역할 카드를 눈으로 확인하는 구간이라 명확히 보여야 한다.
        WerewolfPhase.FINAL_ROLE_REVEAL.value: Scene("ww_reveal", NEUTRAL_WHITE, 100, 800),
        # 승리팀을 모르는 상태가 정상 경로다 (§3.3 결정). 최종 역할 판정이
        # 구현되면 팀 색 분기를 여기에 추가한다.
        WerewolfPhase.RESULT.value: Scene("ww_result", CELEBRATION_GOLD, 100, 1500),
    }


# 요트는 Scene이 항상 중립이고 Cue만 일시적으로 벗어난다. 세 페이즈 모두
# 굴림·킵·득점이 오가는 인식 구간이라 색을 건드리지 않는다.
#
# 키를 문자열로 적지 않고 enum에서 가져오는 이유: 요트 페이즈는 대문자
# ("AWAITING_ROLL")고 늑대인간은 소문자("night_start")라 규약이 다르다.
# 손으로 적으면 오타가 조용히 중립 폴백으로 흡수돼 눈치채기 어렵다.
YACHT_SCENES: dict[str, Scene] = {
    YachtPhase.AWAITING_ROLL.value: NEUTRAL_SCENE,
    YachtPhase.AWAITING_KEEP.value: NEUTRAL_SCENE,
    YachtPhase.AWAITING_SCORE.value: NEUTRAL_SCENE,
    # 종료도 Scene은 기본색이다. 축하는 Cue가 터뜨리고 곧바로 여기로 돌아온다.
    # Scene 자체를 금색으로 두면 축하가 끝나지 않고 그 색에 머무르고, Cue와
    # 색이 같아 중복 제거에 걸려 연출이 통째로 사라진다.
    YachtPhase.GAME_END.value: NEUTRAL_SCENE,
}


# 요트 Cue. 전체 길이(rise+hold+fall)가 CUE 메시지의 duration_ms 안에 들어와야
# 한다 — 모달이 닫히는 순간에는 조명이 이미 중립으로 돌아와 있어야 다음 굴림
# 인식이 안전하다 (§2.4 불변식). 아래 값들은 각각 여유를 두고 잡았다.
#
#   turn_transition  1900ms <= 2200ms
#   highlight        2700ms <= 3000ms
#   game_finish      3800ms <= 4000ms
#
# 좌석별 색을 쓰지 않는 이유: 프론트 좌석 색은 oklch 파스텔(C≈0.12)이라
# 전구 하나로 재현하면 10색이 전부 "살짝 물든 흰색"으로 뭉갠다. 누구 차례인지는
# 화면과 TTS가 이미 말하므로, 조명은 "턴이 넘어갔다"만 분명히 전한다.
# 밝기는 세 Cue 모두 100으로 고정한다. 요트에서 광량이 흔들리면 그대로 인식
# 위험이므로, 변하는 것은 색온도뿐이다.
YACHT_CUES: dict[str, Cue] = {
    "yacht_turn_transition": Cue(
        "turn_sweep", YACHT_SWEEP_WARM, brightness=100, rise_ms=400, hold_ms=900, fall_ms=600
    ),
    # 야찌·라지스트레이트. 사건이므로 더 진하게, 더 길게 간다.
    "yacht_turn_transition_highlight": Cue(
        "score_burst", YACHT_BURST_GOLD, brightness=100, rise_ms=300, hold_ms=1600, fall_ms=800
    ),
    # 게임이 끝났으니 더 굴릴 주사위가 없다. 여기서만 원색을 쓴다.
    "yacht_game_finish": Cue(
        "game_finish", CELEBRATION_GOLD, brightness=100, rise_ms=500, hold_ms=2400, fall_ms=900
    ),
}

# 플레이 중에 재생되는 Cue — 인식 제약을 받는다. 게임 종료 Cue는 제외.
IN_PLAY_YACHT_CUES = ("yacht_turn_transition", "yacht_turn_transition_highlight")


def build_scene_map(night_brightness: int) -> dict[str, dict[str, Scene]]:
    return {
        "werewolf": build_werewolf_scenes(night_brightness),
        "yacht": YACHT_SCENES,
    }


def build_cue_map() -> dict[str, Cue]:
    return dict(YACHT_CUES)
