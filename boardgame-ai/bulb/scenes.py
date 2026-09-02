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
    kelvin: int | None = None  # 흰색 계열이면 색온도로 낸다. 아래 §색온도 참고.
    # 이 Scene으로 들어갈 때 어둠을 한 번 거친다. 아래 §밤 전환 참고.
    enter_via_dark: bool = False

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
    kelvin: int | None = None  # 흰색 계열이면 색온도로 낸다. 아래 §색온도 참고.

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


# ── 색온도 ───────────────────────────────────────────────────────────────────
#
# 흰색에 가까운 색은 RGB가 아니라 색온도로 낸다.
#
# 컬러 전구는 빨강·초록·파랑 다이를 섞어 흰색을 만드는데, 다이별 광량 편차가
# 개체마다 다르다. 채도가 낮을수록 그 편차가 그대로 드러난다 — 전구 2개에 같은
# (255,225,190)을 보냈더니 한쪽은 분홍, 한쪽은 연두로 보였다 (실측). 채도가 높은
# 색은 다이 하나가 지배해서 편차가 잘 안 보이므로 그대로 RGB로 둔다.
#
# 색온도 모드는 전용 백색 LED를 쓴다. 개체 편차가 훨씬 작고, 더 밝고, 연색성이
# 좋다. 실물 지원 범위는 1700~6500K다 (bulb/driver/base.py).
#
# color 값은 지우지 않는다. 그게 여전히 "의도한 색"이고, 화면에 조명을 그리는
# 프론트엔드 드라이버는 색온도를 그릴 방법이 없어 이 값을 쓴다.

# 요트 주사위 인식 조명의 색온도.
#
# 이 값은 곧 카메라가 보는 광원이다. 실물로 확인한 결과 **백색에 가까울수록
# 인식률이 올라간다** — 웜톤이 섞이면 주사위 표면과 검은 눈의 대비가 줄어든다.
# 그래서 전구 상한인 6500K를 쓴다.
#
# 연출용으로는 차갑게 느껴질 수 있지만 요트 구간은 인식이 우선이다(설계문서 §4.7).
# 화면에 그려지는 색은 NEUTRAL_SCENE.color(백색)라 태블릿 쪽 인상은 바뀌지 않는다.
#
# 전구 상한인 6500K를 쓴다. 실물 튜닝에서 여기가 가장 좋았다 — 주사위 5개가
# 전부 확정되고 원본 일치율이 90% 안팎으로 유지된다. 조정은
# tools/tune_dot_counter.py 의 색온도 트랙바로 눈으로 보며 한다.
#
# 상한을 쓰는 대가로 "중립보다 서늘한" 색온도가 없어졌다. 역전 Cue는 그래서
# 색온도를 쓰지 않는다 — 아래 YACHT_UPSET_COOL 주석 참고.
NEUTRAL_KELVIN = 6500

# 어디서 쓰든 안전한 바탕. 인식이 필요한 구간(요트 전 구간, 로비 좌석 등록)의
# 기본값이자, 매핑에 없는 페이즈를 만났을 때의 폴백이다.
NEUTRAL_SCENE = Scene(
    name="neutral",
    color=NEUTRAL_WHITE,
    brightness=100,
    transition_ms=800,
    kelvin=NEUTRAL_KELVIN,
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
# 역전은 따뜻함이 아니라 서늘한 번쩍임으로 간다. 일반 턴의 웜톤과 반대 방향이라
# 같은 광량에서도 "뭔가 다른 일이 났다"가 즉시 읽힌다.
#
# **이 색만 색온도를 쓰지 않는다.** 중립이 전구 상한(6500K)이라 그보다 서늘한
# 색온도가 없다. RGB로 내면 전용 백색 LED 대신 RGB 다이를 쓰게 되는데, 그쪽이
# 더 어둡고 더 푸르러서 6500K 백색과 확실히 갈린다 — 상한에 막힌 상황에서
# "서늘하게 번쩍인다"를 살릴 수 있는 유일한 방법이다.
#
# 흰색 계열을 RGB로 내면 전구마다 색이 갈리는 문제가 있지만, 여기는 2.35초짜리
# 순간 연출이고 전구 2개가 같은 모델이라 감수할 만하다. 오래 유지되는 Scene에는
# 이 예외를 쓰지 않는다.
YACHT_UPSET_COOL: RGB = (196, 226, 255)
# 0점은 색을 거의 빼서 김이 빠지게. 밝기는 못 낮추므로 온도만 식힌다.
YACHT_DEFLATE_GRAY: RGB = (214, 224, 238)

# 위 요트 틴트들의 색온도. 애초에 "색을 갈아엎지 않고 온도만 바꾼다"가 설계
# 의도였으므로 색온도 모드가 그 의도를 그대로 실현한다 — RGB 근사보다 정확하다.
#
# 값을 고르는 기준은 **중립(NEUTRAL_KELVIN)과 얼마나 떨어졌는가**다. 색온도가
# 붙은 명령은 RGB를 무시하므로, 중립과 가까운 값은 색을 아무리 다르게 적어도
# 전구에서 구분되지 않는다. 아래 값들은 서로 그리고 중립과 최소 800K 떨어뜨렸고,
# tests/test_light_kelvin.py 가 이 간격을 검사한다.
#
#   중립      6500K   바탕 (전구 상한)
#   sweep     2900K   일반 턴 — 따뜻하게 훑고 지나간다
#   burst     2000K   특별 족보 — 가장 따뜻한 금빛. 일반 턴과 확실히 갈려야
#                     "이번엔 다른 일이 났다"가 색만으로 읽힌다
#   deflate   4300K   0점 — 따뜻하지도 서늘하지도 않은 밋밋함
#   upset     (RGB)   역전 — 중립이 상한이라 색온도로는 더 서늘해질 수 없다
YACHT_SWEEP_KELVIN = 2900
YACHT_BURST_KELVIN = 2000
YACHT_DEFLATE_KELVIN = 4300

# 늑대인간 새벽. 밤의 원색들 사이에서 유일하게 흰색에 가까워 색온도로 낸다.
DAWN_KELVIN = 3000

# 늑대인간 투표. **이 구간은 인식 구간이다** — 손가락 지목을 MediaPipe가 읽어야
# 투표가 성립한다. 그런데 원색 빨강(255,20,20) 밝기 55로 두었더니 카메라가 받는
# 그림에서 G·B 채널이 거의 비어, 손과 배경이 같은 붉은 덩어리로 뭉갠다.
# MediaPipe는 RGB 세 채널을 다 보고 학습됐으므로 여기서 손을 놓친다.
#
# 그래서 요트와 같은 원칙을 적용한다: 인식이 걸린 구간은 인식이 우선이다.
# 색온도 모드로 바꾸면 전용 백색 LED(광대역)를 쓰므로 세 채널에 모두 신호가
# 남고, 같은 밝기에서 더 밝다. 붉은 기는 색온도를 전구 하한 가까이 내려 얻는다
# — 원색 빨강만큼 강렬하진 않지만 어두운 방에서 충분히 붉게 읽힌다.
VOTE_KELVIN = 2000
# 지목하는 동안의 밝기. 밤의 어둠과 대비되어야 하고, 손이 보여야 한다.
VOTE_BRIGHTNESS = 80
# 화면(LightStrip)이 그릴 색. 전구는 색온도로 나가므로 이 값은 인상만 담당한다.
VOTE_WARM_RED: RGB = (255, 196, 170)


# ── 밤 전환 ──────────────────────────────────────────────────────────────────
#
# 역할이 넘어갈 때 색만 갈아끼우면, 조명은 "장면이 바뀌었다"까지만 말하고
# **눈을 감았다 뜬다는 규칙 자체는 말하지 않는다.** 진행자는 "늑대인간은 눈을
# 감으세요 / 예언자는 눈을 뜨세요"라고 두 번 말하는데 조명은 한 번만 움직인다.
#
# 그래서 어둠을 한 번 거쳐 간다.
#
#   이전 역할 색 ──fall──▶ 소등 ──dark 유지──▶ 다음 역할 색 ──rise──▶
#                        "눈을 감으세요"      "눈을 뜨세요"
#
# 소등 구간이 있어야 눈을 감는 사람이 감았는지 확인할 필요 없이 방이 어둡고,
# 다시 밝아지는 순간이 곧 다음 역할의 신호가 된다.
#
# 이 길이만큼 밤 단계 시간도 늘려야 한다 (games/werewolf/fsm.py의
# PASSIVE_PHASE_DURATION / ACTIVE_PHASE_TIMEOUT). 안 늘리면 조명이 다 오르기
# 전에 다음 단계로 넘어간다.
NIGHT_DIP_FALL_MS = 600   # 이전 역할 색 → 소등
NIGHT_DIP_DARK_MS = 900   # 완전한 어둠 유지
NIGHT_DIP_RISE_MS = 800   # 소등 → 다음 역할 색
NIGHT_DIP_TOTAL_MS = NIGHT_DIP_FALL_MS + NIGHT_DIP_DARK_MS + NIGHT_DIP_RISE_MS


def build_werewolf_scenes(night_brightness: int) -> dict[str, Scene]:
    """늑대인간 페이즈 → Scene.

    키는 games/werewolf/ontology.py 의 WerewolfPhase 값이다. 이 이름은 계약이라
    바꾸려면 조명 담당자와 합의해야 한다 (설계문서 §3.4).

    밤 밝기는 인자로 받는다. 전구 1개가 유일한 광원이라 이 값 하나가 밤의
    어둠을 전적으로 결정하고, "어둡되 최소한 보이긴 해야 한다"는 지점은
    실물로만 찾을 수 있다 (§7.2-8). 현장에서 LIGHT_NIGHT_BRIGHTNESS 로 조정한다.
    """
    night = night_brightness

    def role(name: str, color: RGB) -> Scene:
        """밤 역할 Scene. 전부 어둠을 거쳐 들어간다 (§밤 전환).

        transition_ms는 쓰이지 않는다 — 어둠을 거치는 경로가 자기 페이드 시간을
        따로 갖기 때문이다. 그래도 값을 남겨두는 이유는 enter_via_dark를 끄면
        곧바로 예전 동작(직접 크로스페이드)으로 돌아갈 수 있게 하기 위해서다.
        """
        return Scene(name, color, night, 1200, enter_via_dark=True)

    return {
        # "밤이 되었습니다" — 완전한 암전에서 시작한다. 여기서 각 역할의 색이
        # 스며들어야 장면이 산다. 밤에는 비전이 할 일이 없어 소등해도 잃을 게 없다.
        WerewolfPhase.NIGHT_START.value: BLACKOUT_SCENE,
        WerewolfPhase.NIGHT_DOPPELGANGER.value: role("ww_doppelganger", SPECIAL_PURPLE),
        WerewolfPhase.NIGHT_WEREWOLF.value: role("ww_werewolf", VILLAIN_RED),
        WerewolfPhase.NIGHT_MINION.value: role("ww_minion", VILLAIN_RED_WEAK),
        WerewolfPhase.NIGHT_MASON.value: role("ww_mason", VILLAGE_GREEN),
        WerewolfPhase.NIGHT_SEER.value: role("ww_seer", INFO_INDIGO),
        WerewolfPhase.NIGHT_INSOMNIAC.value: role("ww_insomniac", INFO_INDIGO),
        WerewolfPhase.NIGHT_ROBBER.value: role("ww_robber", TRICK_AMBER),
        WerewolfPhase.NIGHT_TROUBLEMAKER.value: role("ww_troublemaker", TRICK_AMBER),
        WerewolfPhase.NIGHT_DRUNK.value: role("ww_drunk", TRICK_AMBER),
        # ★ 이 게임의 감정적 클라이막스. 어둠에서 따뜻한 빛이 2.5초에 걸쳐
        # 차오르며 TTS가 얹힌다. 프론트 PhaseTransition의 dawn 타입
        # (duration 2500, midAt 300)과 타이밍을 맞춘다.
        WerewolfPhase.DAY_DISCUSSION.value: Scene(
            "ww_dawn", DAWN_WARM, 100, 2500, kelvin=DAWN_KELVIN
        ),
        # 투표 두 페이즈는 인식 구간이다 — 위 VOTE_KELVIN 주석 참고.
        # 밤에서 올라오는 자리라 여기도 어둠을 한 번 거친다: 토론이 끝나고
        # 방이 한 번 잠긴 뒤 붉게 밝아지는 편이 카운트다운의 시작을 분명히 한다.
        WerewolfPhase.VOTE_COUNTDOWN.value: Scene(
            "ww_countdown",
            VOTE_WARM_RED,
            VOTE_BRIGHTNESS,
            2000,
            kelvin=VOTE_KELVIN,
            enter_via_dark=True,
        ),
        WerewolfPhase.VOTE.value: Scene(
            "ww_vote", VOTE_WARM_RED, VOTE_BRIGHTNESS, 1000, kelvin=VOTE_KELVIN
        ),
        # 시스템은 역할을 모르므로 승리팀 색 분기가 없다. 투표 결과를 발표하고
        # 플레이어들이 직접 카드를 공개하는 구간이라 밝게 유지한다.
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
    # 대부분의 턴이 여기로 온다. 모달 없이 화면 안에서만 처리되므로 조명도 짧다.
    "yacht_turn_transition": Cue(
        "turn_sweep",
        YACHT_SWEEP_WARM,
        brightness=100,
        rise_ms=300,
        hold_ms=600,
        fall_ms=500,
        kelvin=YACHT_SWEEP_KELVIN,
    ),
    # 야찌·라지스트레이트 확정. 주사위가 멈춘 순간에 화면이 이미 크게 축하했으므로
    # (yacht_hand_achieved — 조명은 관여하지 않는다) 여기서는 짧게 못 박아준다.
    "yacht_turn_transition_highlight": Cue(
        "score_burst",
        YACHT_BURST_GOLD,
        brightness=100,
        rise_ms=250,
        hold_ms=700,
        fall_ms=600,
        kelvin=YACHT_BURST_KELVIN,
    ),
    # 후반 선두 역전.
    "yacht_turn_transition_lead_change": Cue(
        "upset_flash",
        YACHT_UPSET_COOL,
        brightness=100,
        rise_ms=350,
        hold_ms=1300,
        fall_ms=700,
        # 색온도를 붙이지 않는 유일한 요트 큐. 이유는 YACHT_UPSET_COOL 주석에 있다.
    ),
    # 족보를 0점으로 버렸을 때. 축하가 아니므로 짧게 끝낸다.
    "yacht_turn_transition_zero": Cue(
        "deflate",
        YACHT_DEFLATE_GRAY,
        brightness=100,
        rise_ms=250,
        hold_ms=600,
        fall_ms=400,
        kelvin=YACHT_DEFLATE_KELVIN,
    ),
    # 게임이 끝났으니 더 굴릴 주사위가 없다. 여기서만 원색을 쓴다.
    "yacht_game_finish": Cue(
        "game_finish", CELEBRATION_GOLD, brightness=100, rise_ms=500, hold_ms=2400, fall_ms=900
    ),
}

# 플레이 중에 재생되는 Cue — 인식 제약을 받는다. 게임 종료 Cue는 제외.
IN_PLAY_YACHT_CUES = tuple(name for name in YACHT_CUES if name != "yacht_game_finish")


# ── 컨트롤 세션 ──────────────────────────────────────────────────────────────
#
# 게임이 아니라 조명 자체를 다루는 자리다. 진행자가 버튼을 눌러 방 분위기를
# 바꾼다 — 축하, 약올리기, 박수, 방구, 파티.
#
# 요트·늑대인간 Cue와 형태가 다른 이유: 파티는 색이 **여러 번** 바뀌어야 한다.
# 한 색으로 터지고 마는 Cue로는 표현할 수 없어서, 색 여러 개를 순서대로 밟는
# 형태로 정의한다. 색이 하나뿐인 큐는 단계가 하나인 특수한 경우일 뿐이다.
#
# 끝나면 반드시 직전 Scene으로 돌아온다 — 컨트롤 세션에서는 그 Scene이
# 사용자가 슬라이더로 맞춰 둔 색이다.


@dataclass(frozen=True)
class ControlCue:
    """색 여러 개를 순서대로 밟고 Scene으로 돌아오는 연출.

    steps  : (색, 그 색을 유지할 ms) 목록. 하나면 단색 연출.
    sfx    : 함께 재생할 효과음 이름 (audio/catalog.py의 SFX_REGISTRY 키).
    """

    name: str
    label: str
    steps: tuple[tuple[RGB, int], ...]
    brightness: int
    sfx: str
    fall_ms: int = 600

    @property
    def total_ms(self) -> int:
        return sum(hold for _color, hold in self.steps) + self.fall_ms


# 파티 색 순환. 색상환을 고르게 돌아 "막 바뀐다"가 읽히게 한다.
_PARTY_COLORS: tuple[RGB, ...] = (
    (255, 40, 90),
    (255, 170, 30),
    (250, 240, 60),
    (60, 220, 120),
    (40, 190, 255),
    (150, 80, 255),
)

CONTROL_CUES: dict[str, ControlCue] = {
    "celebrate": ControlCue(
        name="celebrate",
        label="축하",
        steps=(
            (CELEBRATION_GOLD, 420),
            ((255, 235, 170), 320),
            (CELEBRATION_GOLD, 420),
        ),
        brightness=100,
        sfx="control_celebrate",
        fall_ms=700,
    ),
    # 약올리기 — 짓궂은 자주색이 깜빡인다. 축하와 반대 방향의 색이라 헷갈리지 않는다.
    "tease": ControlCue(
        name="tease",
        label="약올리기",
        steps=(
            ((255, 60, 200), 240),
            ((90, 20, 120), 200),
            ((255, 60, 200), 240),
            ((90, 20, 120), 200),
            ((255, 60, 200), 300),
        ),
        brightness=85,
        sfx="control_tease",
        fall_ms=500,
    ),
    # 박수 — 노란 조명. 색은 사용자가 지정했다.
    "applause": ControlCue(
        name="applause",
        label="박수",
        steps=(((255, 214, 70), 1500),),
        brightness=100,
        sfx="control_applause",
        fall_ms=700,
    ),
    # 방구 — 탁한 연두. 밝기를 낮춰 "가라앉는" 느낌을 준다.
    "fart": ControlCue(
        name="fart",
        label="방구",
        steps=(((150, 190, 60), 900), ((110, 150, 50), 700)),
        brightness=55,
        sfx="control_fart",
        fall_ms=900,
    ),
    # 파티 — 색상환을 두 바퀴 돈다. 다른 것들보다 확실히 길다(약 9초).
    "party": ControlCue(
        name="party",
        label="파티",
        steps=tuple((c, 380) for c in _PARTY_COLORS * 4),
        brightness=100,
        sfx="control_party",
        fall_ms=1000,
    ),
}


def build_control_cue_map() -> dict[str, ControlCue]:
    return dict(CONTROL_CUES)


# ── 발표 연출 ────────────────────────────────────────────────────────────────
#
# 관리자 콘솔의 버튼 하나가 방을 어떻게 움직이는지. 조명 정의를 새로 만들지
# 않고 위의 게임 정의를 조립만 한다 — 재현하려는 것이 실제 게임의 그 순간이라,
# 여기서 따로 만들면 게임 쪽 값을 고쳤을 때 발표용만 옛 색으로 남는다.


# 발표 콘솔의 바탕. 로비와 같은 백색이다 — 관리자 화면에 들어갔다는 이유로
# 방 조명이 달라지면, 발표자는 아무것도 안 했는데 무대가 먼저 바뀐다.
#
# NEUTRAL_SCENE과 색·밝기가 같고 페이드만 길다. 여기로 돌아오는 자리가 대부분
# 밤 색(밝기 15)이라, 게임용 800ms로 백색 100%까지 올리면 눈이 부시다.
SHOW_REST_SCENE = Scene(
    name="show_rest",
    color=NEUTRAL_WHITE,
    brightness=100,
    transition_ms=1500,
    kelvin=NEUTRAL_KELVIN,
)

# 발표 연출의 암전 페이드. 게임의 밤 전환과 같은 값을 쓴다(NIGHT_DIP_FALL_MS).
SHOW_DARK_FALL_MS = NIGHT_DIP_FALL_MS


@dataclass(frozen=True)
class ShowLight:
    """발표 버튼 하나의 조명 계획.

        방을 재우고(dark_ms) → scene 을 올리고 → cue 를 터뜨리고
        → 목소리가 끝나면 rest 로 물러난다.

    **dark_ms가 필요한 이유.** 늑대인간 밤은 "눈을 감으세요 / 뜨세요"가 한
    쌍이다. 밝은 방에서 곧바로 붉은색으로 갈아끼우면 조명이 뒤쪽만 말한다.
    한 번 재웠다 올려야 앞쪽까지 조명이 말해준다. 게임의 밤 전환과 같은
    구조인데(Scene.enter_via_dark), 여기서는 어둠의 길이와 목소리가 들어오는
    시점을 맞춰야 해서 직접 잡는다.

    **rest가 None이면 scene에 머문다.** 요트 큐처럼 스스로 제자리로 돌아오는
    연출이 그렇다. 밤 색은 스스로 돌아올 데가 없어서 rest를 준다 — 목소리가
    끝났는데 방이 계속 붉으면 그때부터는 연출이 아니라 그냥 붉은 방이다.
    물러나는 시점을 여기서 숫자로 잡지 않는 이유는, 그게 **목소리가 끝나는
    때**라서다. 목소리 길이는 음원 파일이 알고 있다(backend/show_acts.py).
    """

    scene: Scene
    cue: Cue | None = None
    dark_ms: int = 0
    rest: Scene | None = None

    @property
    def enter_ms(self) -> int:
        """버튼을 누르고 색이 오르기 시작할 때까지. 소리도 이때 들어온다."""
        return SHOW_DARK_FALL_MS + self.dark_ms if self.dark_ms > 0 else 0

    @property
    def total_ms(self) -> int:
        """색이 제자리에 설 때까지. rest는 목소리가 정하므로 빠진다."""
        total = self.enter_ms + self.scene.transition_ms
        if self.cue is not None:
            total += self.cue.total_ms
        return total


def build_scene_map(night_brightness: int) -> dict[str, dict[str, Scene]]:
    return {
        "werewolf": build_werewolf_scenes(night_brightness),
        "yacht": YACHT_SCENES,
    }


def build_cue_map() -> dict[str, Cue]:
    return dict(YACHT_CUES)
