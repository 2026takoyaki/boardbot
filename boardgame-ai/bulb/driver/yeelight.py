"""실제 Yeelight 전구 제어. 환경변수로 opt-in.

python-yeelight은 동기 소켓 라이브러리라 그대로 부르면 이벤트 루프가 멈춘다.
모든 호출을 스레드로 넘긴다.

실물 검증: Yeelight color fw 65 두 대 (tools/light_check.py).

시연 당일 함정:
    - Mi Home 앱에서 "LAN 제어"를 켜야만 접속된다. **기본이 꺼져 있다.**
    - 2.4GHz 전용. 아이폰 핫스팟은 "호환성 최대화"를 켜야 한다.
    - 제어 포트는 55443 고정.
    - 전구당 분당 약 60개 명령 제한. 넘기면 한동안 모든 명령을 거부한다.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

from bulb.driver.base import (
    KELVIN_MAX,
    KELVIN_MIN,
    MAX_FLOW_TRANSITIONS,
    MIN_FLOW_STEP_MS,
    RGB,
    LightDriver,
    SequenceStep,
    flow_period,
)

logger = logging.getLogger(__name__)

class _FlowLengthWarningFilter(logging.Filter):
    """python-yeelight의 "up to 9 transitions" 경고를 걸러낸다.

    라이브러리가 모델 표에서 읽은 값인데 실물과 다르다 — color fw 65는 16개를
    받는다(base.MAX_FLOW_TRANSITIONS). 연출마다 찍혀 진짜 경고를 묻는다.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        return "transitions. Your" not in record.getMessage()


logging.getLogger("yeelight").addFilter(_FlowLengthWarningFilter())
logging.getLogger("yeelight.flow").addFilter(_FlowLengthWarningFilter())

_MIN_DURATION_MS = MIN_FLOW_STEP_MS


class YeelightDriver(LightDriver):
    """LAN 직접 제어. 클라우드를 경유하지 않는다.

    연결은 지연 생성한다 — 생성 시점에 전구가 아직 안 붙어 있어도 서버가
    떠야 하고, 조명이 서버 부팅을 막을 이유가 없다.
    """

    def __init__(self, ip: str) -> None:
        self._ip = ip
        self._bulb: object | None = None

    @property
    def ip(self) -> str:
        return self._ip

    def _ensure_bulb(self) -> object:
        if self._bulb is None:
            from yeelight import Bulb  # 선택 의존성. 없으면 여기서 ImportError.

            # effect="smooth": 급격한 전환은 싸구려 느낌이 난다.
            self._bulb = Bulb(self._ip, effect="smooth", duration=1000, auto_on=False)
        return self._bulb

    def _apply_sync(
        self, color: RGB, brightness: int, duration_ms: int, kelvin: int | None
    ) -> None:
        bulb = self._ensure_bulb()

        if brightness <= 0:
            # 0은 최저 밝기가 아니라 소등이다. 늑대인간 밤은 여기서 시작한다.
            bulb.turn_off(duration=max(_MIN_DURATION_MS, duration_ms))  # type: ignore[attr-defined]
            return

        # 색·밝기·전원을 **명령 하나**로 보낸다.
        #
        # 예전에는 turn_on → set_rgb → set_brightness 세 번이었다. 전구는 분당
        # 명령 수를 세다가 약 60개에서 끊는데(client quota exceeded), 색 한 번에
        # 세 개씩 쓰면 파티 큐 한 번으로 넘긴다. 넘긴 뒤에는 복귀 명령까지
        # 거부돼 방이 마지막 색에 멈춘다 — 2026-11-11 실물에서 그대로 겪었다.
        #
        # set_scene은 꺼져 있으면 켜면서 적용하므로 turn_on도 따로 필요 없다.
        # 단계 하나짜리 흐름(color flow)으로 보내는 이유는 전환 시간을 실을 수
        # 있는 set_scene 형식이 이것뿐이어서다.
        self._start_flow(bulb, [self._transition(color, brightness, duration_ms, kelvin)])

    def _play_sequence_sync(self, steps: Sequence[SequenceStep], brightness: int) -> None:
        from yeelight.flow import SleepTransition

        period, repeats = flow_period(steps)
        transitions: list[object] = []
        for step in period:
            fade = max(_MIN_DURATION_MS, min(step.transition_ms, step.hold_ms))
            rest = step.hold_ms - fade
            if rest < _MIN_DURATION_MS:
                # 머무를 시간이 전구가 받는 최소 단위보다 짧으면 넘어가기에
                # 붙인다. 버리면 박자가 그만큼 당겨져 효과음과 어긋난다.
                fade, rest = step.hold_ms, 0
            level = step.brightness if step.brightness is not None else brightness
            transitions.append(self._transition(step.color, level, fade, None))
            if rest:
                transitions.append(SleepTransition(duration=rest))
        if not transitions:
            return
        if len(transitions) > MAX_FLOW_TRANSITIONS:
            # 보내 봐야 전구가 invalid command로 거부한다. 무엇이 문제인지
            # 여기서 말해 둔다 — 전구 쪽 에러만으로는 원인을 짐작하기 어렵다.
            raise ValueError(
                f"흐름 전환 {len(transitions)}개 — 전구는 {MAX_FLOW_TRANSITIONS}개까지 받는다. "
                "연출을 반복 패턴으로 만들거나 단계를 줄여야 한다."
            )
        self._start_flow(self._ensure_bulb(), transitions, repeats)

    @staticmethod
    def _transition(
        color: RGB, brightness: int, duration_ms: int, kelvin: int | None
    ) -> object:
        from yeelight.flow import RGBTransition, TemperatureTransition

        duration = max(_MIN_DURATION_MS, duration_ms)
        level = max(1, min(100, brightness))
        if kelvin is not None:
            # 흰색 계열. 전용 백색 LED를 쓴다 — RGB 혼색보다 개체 편차가 작다.
            temp = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
            return TemperatureTransition(temp, duration=duration, brightness=level)
        red, green, blue = color
        return RGBTransition(red, green, blue, duration=duration, brightness=level)

    @staticmethod
    def _start_flow(bulb: object, transitions: list[object], repeats: int = 1) -> None:
        from yeelight import Flow, SceneClass

        # 한 번 돌고 마지막 상태에 머문다. 원래 색으로 돌아가는 일(recover)은
        # 전구에 맡기지 않는다 — 돌아갈 자리는 LightController가 알고 있다
        # (연출 도중에 사용자가 슬라이더로 바탕색을 바꿀 수도 있다).
        flow = Flow(count=repeats, action=Flow.actions.stay, transitions=transitions)
        bulb.set_scene(SceneClass.CF, flow)  # type: ignore[attr-defined]

    async def apply(
        self,
        color: RGB,
        brightness: int,
        duration_ms: int,
        kelvin: int | None = None,
    ) -> None:
        await asyncio.to_thread(self._apply_sync, color, brightness, duration_ms, kelvin)

    supports_sequence = True

    async def play_sequence(
        self,
        steps: Sequence[SequenceStep],
        brightness: int,
        alt: Sequence[SequenceStep] | None = None,
    ) -> None:
        """시퀀스 전체를 명령 하나로 넘긴다. 진행은 전구가 한다. alt는 무시한다."""
        await asyncio.to_thread(self._play_sequence_sync, steps, brightness)

    async def close(self) -> None:
        bulb = self._bulb
        self._bulb = None
        if bulb is None:
            return
        with_suppress = getattr(bulb, "_socket", None)
        if with_suppress is None:
            return
        try:
            await asyncio.to_thread(with_suppress.close)
        except Exception:
            logger.debug("light: yeelight 소켓 정리 실패", exc_info=True)
