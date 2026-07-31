"""전구 조명 연출.

    from bulb import build_controller
    controller = build_controller(broadcast=ws_manager.broadcast)
    controller.on_message(message, game="werewolf")

센서(카메라) → 판정(FSM) → 액추에이터(조명)의 폐루프를 닫는 마지막 조각이다.
물리 세계를 읽기만 하던 시스템이 물리 세계에 개입하게 된다.
"""

from __future__ import annotations

import logging

from bulb.config import LightConfig
from bulb.controller import LightController
from bulb.driver.base import LightDriver
from bulb.driver.frontend import BroadcastFn, FrontendDriver
from bulb.driver.mock import MockDriver
from bulb.scenes import BLACKOUT_SCENE, NEUTRAL_SCENE, Cue, Scene

logger = logging.getLogger(__name__)

__all__ = [
    "BLACKOUT_SCENE",
    "NEUTRAL_SCENE",
    "Cue",
    "LightConfig",
    "LightController",
    "LightDriver",
    "Scene",
    "build_controller",
    "build_driver",
]


def build_driver(config: LightConfig, broadcast: BroadcastFn | None = None) -> LightDriver:
    """설정대로 드라이버를 만들되, 못 만들면 조용히 내려앉는다.

    전구 연결 실패가 서버 부팅을 막아서는 안 된다. yeelight → frontend → mock
    순으로 폴백하므로 어떤 환경에서도 컨트롤러는 만들어진다.
    """
    name = config.driver

    if name == "yeelight":
        if not config.bulb_ip:
            logger.warning("light: LIGHT_BULB_IP가 없어 yeelight 드라이버를 쓸 수 없다.")
        else:
            try:
                from bulb.driver.yeelight import YeelightDriver

                return YeelightDriver(config.bulb_ip)
            except ImportError:
                logger.warning("light: python-yeelight 미설치. 폴백한다.")

    if name in ("yeelight", "frontend"):
        if broadcast is not None:
            return FrontendDriver(broadcast)
        logger.warning("light: broadcast 콜백이 없어 frontend 드라이버를 쓸 수 없다.")

    return MockDriver()


def build_controller(
    config: LightConfig | None = None,
    broadcast: BroadcastFn | None = None,
) -> LightController:
    """환경변수 기준으로 컨트롤러 조립. 매핑 테이블은 기본값을 쓴다."""
    resolved = config if config is not None else LightConfig.from_env()
    driver = build_driver(resolved, broadcast)
    logger.info(
        "light: %s 드라이버로 시작 (enabled=%s)", type(driver).__name__, resolved.enabled
    )
    return LightController(driver, resolved)
