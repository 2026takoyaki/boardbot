"""실제 Yeelight 전구 제어. 환경변수로 opt-in.

python-yeelight은 동기 소켓 라이브러리라 그대로 부르면 이벤트 루프가 멈춘다.
모든 호출을 스레드로 넘긴다.

⚠️ 아직 실물 전구로 검증하지 않았다. 전구 입수 후 tools/light_check.py 로
확인해야 한다 (설계문서 §9).

시연 당일 함정:
    - Mi Home 앱에서 "LAN 제어"를 켜야만 접속된다. **기본이 꺼져 있다.**
    - 2.4GHz 전용. 아이폰 핫스팟은 "호환성 최대화"를 켜야 한다.
    - 제어 포트는 55443 고정.
"""

from __future__ import annotations

import asyncio
import logging

from bulb.driver.base import KELVIN_MAX, KELVIN_MIN, RGB, LightDriver

logger = logging.getLogger(__name__)


class YeelightDriver(LightDriver):
    """LAN 직접 제어. 클라우드를 경유하지 않는다.

    연결은 지연 생성한다 — 생성 시점에 전구가 아직 안 붙어 있어도 서버가
    떠야 하고, 조명이 서버 부팅을 막을 이유가 없다.
    """

    def __init__(self, ip: str) -> None:
        self._ip = ip
        self._bulb: object | None = None

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
        # Yeelight의 전환 시간 하한이 30ms다. 그 아래는 무시되거나 거부된다.
        duration = max(30, duration_ms)

        if brightness <= 0:
            # 0은 최저 밝기가 아니라 소등이다. 늑대인간 밤은 여기서 시작한다.
            bulb.turn_off(duration=duration)  # type: ignore[attr-defined]
            return

        bulb.turn_on(duration=duration)  # type: ignore[attr-defined]
        if kelvin is not None:
            # 흰색 계열. 전용 백색 LED를 쓴다 — RGB 혼색보다 개체 편차가 작다.
            temp = max(KELVIN_MIN, min(KELVIN_MAX, kelvin))
            bulb.set_color_temp(temp, duration=duration)  # type: ignore[attr-defined]
        else:
            red, green, blue = color
            bulb.set_rgb(red, green, blue, duration=duration)  # type: ignore[attr-defined]
        # set_brightness는 1~100만 받는다.
        bulb.set_brightness(max(1, min(100, brightness)), duration=duration)  # type: ignore[attr-defined]

    async def apply(
        self,
        color: RGB,
        brightness: int,
        duration_ms: int,
        kelvin: int | None = None,
    ) -> None:
        await asyncio.to_thread(self._apply_sync, color, brightness, duration_ms, kelvin)

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
