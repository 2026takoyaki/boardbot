"""발표 연출 — 버튼 하나에 조명·목소리·효과음을 묶어 둔 것.

발표에서 시스템을 보여주려면 그 순간까지 게임을 굴려야 한다. 늑대인간 밤을
보여주려면 사람을 앉히고 카드를 돌리고 역할 안내를 지나야 하는데, 발표 시간에
그럴 자리가 없다. 대신 **그 순간만 떼어** 버튼 하나로 재현한다.

버튼을 누르면 셋이 함께 나간다.

    조명    실제 게임이 그 순간에 쓰는 Scene/Cue를 **그대로** 가져다 쓴다.
            비슷하게 다시 만들지 않는다 — 그러면 게임 쪽 값을 고쳤을 때
            발표용만 옛 색으로 남고, 그 사실을 발표장에서 알게 된다.
    목소리  미리 만들어 둔 음원 파일을 튼다. 합성하지 않는다.
    효과음  게임이 쓰는 SFX를 그대로 쓴다.

## 왜 합성하지 않는가

발표장에서 실패할 수 있는 것을 전부 뺀다. 실시간 합성은 인터넷과 API 키와
Typecast 서버가 모두 살아 있어야 성립하는데, 그 셋 중 하나만 어긋나도 버튼이
조용해진다. 캐시에 기대는 것도 같은 이유로 위험하다 — 캐시 키에 목소리 설정이
들어가서, 페르소나 정의를 한 글자만 손봐도 전부 미스가 된다.

음원은 저장소에 함께 들어간다(audio/assets/show/). 만드는 법:

    python3 tools/generate_show_voices.py

문장이나 페르소나를 바꾸면 그 파일도 다시 만들어야 한다. 안 만들면 화면 자막과
실제 목소리가 다른 말을 한다 — 위 도구가 그 어긋남을 검사한다.
"""

from __future__ import annotations

import logging
import wave
from dataclasses import dataclass, replace
from pathlib import Path

from agents.personas import get_persona
from audio.catalog import show_voice_path, show_voice_url
from bulb.config import LightConfig
from bulb.scenes import (
    NEUTRAL_SCENE,
    SHOW_REST_SCENE,
    YACHT_CUES,
    Scene,
    ShowLight,
    build_werewolf_scenes,
)
from core.persona import DELIVERY_EXCITED, VoiceConfig
from games.werewolf.ontology import WerewolfPhase

logger = logging.getLogger(__name__)

# 효과음이 목소리 앞에 한 번 깔린다. 길이를 알 수 없어서(mp3라 헤더를 읽어야
# 한다) 넉넉히 잡아 둔다 — 버튼 잠금이 실제 연출보다 먼저 풀리면 발표자가
# 두 번 눌러 조명이 중간에 다시 시작한다.
_SFX_ALLOWANCE_MS = 1500

# 효과음이 끝나기 이만큼 전에 목소리가 시작한다.
#
# 효과음이 완전히 끝나고 나서 말이 시작하면 그 사이가 빈다 — 늑대 울음이
# 잦아들고 한 박자 쉰 뒤에 진행자가 입을 여는 것으로 들린다. 울음 끝물에
# 말이 얹혀야 한 덩어리로 들린다.
#
# 겹치기는 화면이 한다(frontend/src/pages/AdminConsole.jsx). 백엔드 오디오 큐는
# 한 번에 하나만 재생하도록 만들어져 있어서(태블릿이 Audio 하나를 돌려쓴다)
# 여기서는 겹칠 방법이 없다.
_VOICE_OVERLAP_MS = 500

# 밤 재현의 암전 — 색이 오르기 전에 방을 재워두는 시간. 페이드는 여기 포함되지
# 않는다(ShowLight.enter_ms). 소리도 이 뒤에 들어온다.
_NIGHT_DARK_MS = 1000

# 밤 색이 차오르는 시간. 게임보다 느리게 잡는다 — 게임에서는 진행이 밀리면
# 안 되지만 발표에서는 이 차오름 자체가 보여줄 것이다.
_NIGHT_RISE_MS = 2200


def _night_show(scene: Scene) -> Scene:
    """게임의 밤 Scene을 발표용으로 손본다.

    어둠은 ShowLight가 직접 만든다(enter_via_dark를 끄는 이유). 게임 쪽 경로는
    어둠의 길이가 고정이라, 소리가 들어오는 시점을 거기에 맞출 수가 없다.
    """
    return replace(scene, enter_via_dark=False, transition_ms=_NIGHT_RISE_MS)


@dataclass(frozen=True)
class ShowAct:
    """발표 버튼 하나.

    id는 음원 파일 이름이기도 하다(audio/assets/show/<id>.wav). 바꾸면 파일도
    같이 바꿔야 한다.
    """

    id: str
    label: str  # 버튼에 찍히는 이름
    hint: str  # 그 아래 한 줄. 무엇이 재현되는지
    persona_id: str  # agents/personas.py 의 키
    text: str  # 화면 자막이자 음원을 만들 때 쓴 원문
    sfx: str  # SFX_REGISTRY 키. 빈 문자열이면 효과음 없음
    light: ShowLight  # 방을 어떻게 몰고 갈지 (bulb/scenes.py)
    # 말투. 빈 문자열이면 그 페르소나의 기본 말투.
    delivery: str = ""
    # 효과음이 끝나기 이만큼 전에 목소리가 시작한다. 위 상수 주석 참고.
    voice_overlap_ms: int = _VOICE_OVERLAP_MS

    @property
    def voice_url(self) -> str:
        return show_voice_url(self.id)

    @property
    def voice_path(self) -> Path:
        return show_voice_path(self.id)

    def voice(self) -> VoiceConfig:
        """이 대사를 합성할 때 쓴(그리고 다시 만들 때도 써야 하는) 목소리."""
        return get_persona(self.persona_id).voice_for(self.delivery or None)

    @property
    def persona_name(self) -> str:
        return get_persona(self.persona_id).display_name

    @property
    def light_ms(self) -> int:
        """색이 제자리에 설 때까지."""
        return self.light.total_ms

    @property
    def audio_delay_ms(self) -> int:
        """버튼을 누르고 소리가 나기까지.

        조명이 색을 올리기 시작하는 순간과 같다. 암전을 두는 연출에서는 그
        어둠이 끝나는 지점이고, 나머지는 0이다. 두 값을 따로 두면 어둠을
        늘렸을 때 소리만 옛 타이밍에 남는다.
        """
        return self.light.enter_ms

    def duration_ms(self) -> int:
        """대략의 전체 길이. 화면이 "몇 초짜리"라고 적어 두는 데 쓴다.

        정확한 종료 시점은 알 수 없다 — 효과음이 mp3라 길이를 읽으려면 헤더를
        파싱해야 하고, 목소리가 그 위에 얼마나 겹칠지는 그 길이에 달렸다.
        실제로 버튼이 풀리는 시점은 **목소리가 끝났을 때**이고, 그건 태블릿이
        안다(frontend/src/pages/AdminConsole.jsx).
        """
        voice_ms = _wav_duration_ms(self.voice_path)
        if voice_ms == 0:
            return self.light_ms
        spoken = self.audio_delay_ms + voice_ms + (_SFX_ALLOWANCE_MS if self.sfx else 0)
        return max(self.light_ms, spoken)


def _wav_duration_ms(path: Path) -> int:
    """wav 길이(ms). 읽을 수 없으면 0.

    발표 직전에 파일을 갈아끼웠는데 그게 깨진 wav여도 서버가 뜨는 것이 먼저다.
    """
    try:
        with wave.open(str(path), "rb") as handle:
            rate = handle.getframerate()
            if rate <= 0:
                return 0
            return int(handle.getnframes() * 1000 / rate)
    except (OSError, wave.Error):
        return 0


def build_show_acts(night_brightness: int | None = None) -> tuple[ShowAct, ...]:
    """발표 버튼 목록.

    야간 밝기를 인자로 받는 이유: 늑대인간 밤 색은 그 값 하나로 정해지는데,
    그 값은 현장에서 환경변수로 조정된다(LIGHT_NIGHT_BRIGHTNESS). 여기서 따로
    상수를 들고 있으면 조정한 밝기가 발표 버튼에만 반영되지 않는다.
    """
    if night_brightness is None:
        night_brightness = LightConfig.from_env().night_brightness
    night_scenes = build_werewolf_scenes(night_brightness)

    def night(phase: WerewolfPhase) -> ShowLight:
        """밤 역할 재현. 재웠다가 천천히 색을 올리고, 말이 끝나면 물러난다."""
        return ShowLight(
            scene=_night_show(night_scenes[phase.value]),
            dark_ms=_NIGHT_DARK_MS,
            rest=SHOW_REST_SCENE,
        )

    return (
        # ── 늑대인간 밤 ──
        # 밝은 방에서 곧바로 붉은색으로 갈아끼우면 조명이 "눈을 뜨세요"만 말한다.
        # 한 번 재웠다 올려야 "눈을 감으세요"까지 조명이 말해준다. 소리도 그
        # 어둠이 끝나는 지점, 즉 색이 차오르기 시작할 때 들어온다.
        #
        #   밝음 ──재움──▶ 암전 1초 ──▶ 붉게 차오름(2.2초) + 늑대 울음·멘트
        #                                        ──멘트 끝──▶ 백색으로 복귀
        ShowAct(
            id="ww_werewolf",
            label="늑대인간 기상",
            hint="밤 · 늑대인간이 서로를 확인하는 순간",
            persona_id="basic",
            text="늑대인간은 일어나세요. 서로를 확인하고 다시 눈을 감으세요.",
            sfx="wolf_sound",
            light=night(WerewolfPhase.NIGHT_WEREWOLF),
            # 늑대 울음이 7초라, 다 끝나고 말하면 그 사이가 통째로 빈다.
            # 울음이 잦아드는 구간에 멘트를 얹는다.
            voice_overlap_ms=2500,
        ),
        ShowAct(
            id="ww_seer",
            label="예언자 기상",
            hint="밤 · 예언자가 카드를 확인하는 순간",
            persona_id="basic",
            text="예언자는 일어나세요. 다른 플레이어 1명 또는 중앙 카드 2장을 확인할 수 있습니다.",
            sfx="seer_chime",
            light=night(WerewolfPhase.NIGHT_SEER),
        ),
        # ── 요트 ──
        # 요트는 **지나가는 순간**이다. 이 전구가 곧 주사위 인식 조명이라 바탕이
        # 항상 백색이고, 연출은 그 위에 잠깐 얹혔다 스스로 돌아온다. 콘솔의
        # 바탕도 같은 백색이라 큐만 얹으면 실제 게임과 똑같이 보인다.
        ShowAct(
            id="yacht_score",
            label="요트 득점",
            hint="특별한 족보를 넣었을 때 · 금빛으로 번쩍",
            persona_id="shagal",
            delivery=DELIVERY_EXCITED,
            text="샤갈! 라지 스트레이트 30점입니다. 이게 되네요.",
            sfx="score_normal",
            light=ShowLight(
                scene=NEUTRAL_SCENE,
                cue=YACHT_CUES["yacht_turn_transition_highlight"],
            ),
        ),
        ShowAct(
            id="yacht_upset",
            label="요트 역전",
            hint="후반에 1등이 바뀌었을 때 · 서늘하게 번쩍",
            persona_id="angry",
            delivery=DELIVERY_EXCITED,
            text="야 역전이잖아. 1등 바뀌었다고. 이러다 다 뒤집힌다.",
            sfx="lead_change",
            light=ShowLight(
                scene=NEUTRAL_SCENE,
                cue=YACHT_CUES["yacht_turn_transition_lead_change"],
            ),
        ),
        # ── 전략 에이전트 ──
        # 조명이 움직이지 않는 유일한 버튼이다. 실제 게임에서도 전략 조언에는
        # 조명 큐가 없다 — 굴림 결과를 보고 얹는 말이라 사건이 아니고, 요트
        # 구간은 어차피 백색 인식 조명이 유지되어야 한다. 여기서 없는 연출을
        # 만들어 붙이면 발표에서 보여준 것과 실물이 달라진다.
        ShowAct(
            id="strategy",
            label="전략 조언",
            hint="주사위를 읽고 다음 수를 짚어줄 때 · 조명은 그대로",
            persona_id="chungcheong",
            # 실제 게임의 코치 멘트 두 줄을 그대로 이어 쓴다
            # (coach.reroll_mechanic + coach.hand_small_straight_chase).
            #
            # 발표용으로 새 문장을 지어내지 않는 이유가 둘이다. 하나는 여기서도
            # 같은 원칙 — 보여주는 것이 실물과 같아야 한다. 다른 하나는 현실적인
            # 것으로, 이미 합성돼 캐시에 있는 문장이라 Typecast가 막혀도 음원을
            # 만들 수 있다(tools/assemble_show_voice.py).
            #
            # **문장을 고치면 음원도 다시 만들어야 한다.** 아래 두 줄은 캐시에
            # 있는 원문과 글자 하나까지 같아야 조립이 된다.
            text=(
                "남길 주사위는 트레이 한쪽 킵 존으로 옮겨두고, 나머지만 다시 굴리면 되는 겨. "
                "남은 한 개를 다시 굴려서 다섯 개를 잇는 라지 스트레이트 30점을 노려볼 수도 있슈."
            ),
            sfx="dice_recognized",
            light=ShowLight(scene=NEUTRAL_SCENE),
        ),
    )
