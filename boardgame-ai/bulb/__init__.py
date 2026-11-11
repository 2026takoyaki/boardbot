"""전구 조명 연출.

    from bulb import build_controller
    controller = build_controller(broadcast=ws_manager.broadcast)
    controller.on_message(message, game="werewolf")

센서(카메라) → 판정(FSM) → 액추에이터(조명)의 폐루프를 닫는 마지막 조각이다.
물리 세계를 읽기만 하던 시스템이 물리 세계에 개입하게 된다.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from bulb import discovery
from bulb.config import LightConfig
from bulb.controller import LightController
from bulb.driver.base import LightDriver
from bulb.driver.frontend import BroadcastFn, FrontendDriver
from bulb.driver.mock import MockDriver
from bulb.driver.multi import MultiDriver
from bulb.scenes import (
    BLACKOUT_SCENE,
    NEUTRAL_SCENE,
    Cue,
    Scene,
    build_cue_map,
    build_scene_map,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BLACKOUT_SCENE",
    "NEUTRAL_SCENE",
    "Cue",
    "LightConfig",
    "LightController",
    "LightDriver",
    "MultiDriver",
    "Scene",
    "build_controller",
    "build_driver",
    "driver_ips",
    "reconnect",
]


def build_driver(config: LightConfig, broadcast: BroadcastFn | None = None) -> LightDriver:
    """설정대로 드라이버를 만들되, 못 만들면 조용히 내려앉는다.

    전구 연결 실패가 서버 부팅을 막아서는 안 된다. yeelight → frontend → mock
    순으로 폴백하므로 어떤 환경에서도 컨트롤러는 만들어진다.

    IP가 여러 개면 MultiDriver로 묶는다. 위쪽(LightController)에서 보면 전구가
    1개일 때와 완전히 같으므로 연출 코드는 개수를 몰라도 된다.
    """
    name = config.driver

    if name == "yeelight":
        if not config.bulb_ips:
            logger.warning("light: LIGHT_BULB_IP가 없어 yeelight 드라이버를 쓸 수 없다.")
        else:
            try:
                from bulb.driver.yeelight import YeelightDriver

                bulbs = [YeelightDriver(ip) for ip in config.bulb_ips]
                return bulbs[0] if len(bulbs) == 1 else MultiDriver(bulbs)
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
        "light: %s 드라이버로 시작 (전구 %d개, enabled=%s, 밤 밝기=%d)",
        type(driver).__name__,
        len(resolved.bulb_ips) or 1,
        resolved.enabled,
        resolved.night_brightness,
    )
    return LightController(
        driver,
        resolved,
        scene_map=build_scene_map(resolved.night_brightness),
        cue_map=build_cue_map(),
    )


def driver_ips(driver: LightDriver) -> list[str]:
    """이 드라이버가 실제로 명령을 보내는 전구 IP. 실물 전구가 아니면 빈 목록."""
    from bulb.driver.yeelight import YeelightDriver

    if isinstance(driver, MultiDriver):
        return [ip for d in driver.drivers for ip in driver_ips(d)]
    if isinstance(driver, YeelightDriver):
        return [driver.ip]
    return []


async def reconnect(controller: LightController) -> dict[str, Any]:
    """전구를 다시 찾아 붙이고 상태를 돌려준다. 서버 부팅과 관리자 콘솔이 부른다.

    적힌 IP(LIGHT_BULB_IP)가 전부 닿으면 아무것도 바꾸지 않는다. 안 닿으면
    네트워크를 훑어(bulb/discovery.py) 찾은 IP로 드라이버를 갈아 끼우고 현재
    Scene을 다시 보낸다. 아무것도 못 찾으면 그대로 둔다 — 전구가 아직 핫스팟에
    붙는 중일 수 있고, 붙으면 적힌 IP로 그대로 동작한다.

    실물 전구 모드(LIGHT_DRIVER=yeelight)가 아니면 찾지 않는다.

    Returns:
        화면에 그대로 보낼 상태. {"driver", "expected", "active", "source", "ok"}
    """
    config = controller.config
    if config.driver != "yeelight":
        return {
            "driver": config.driver,
            "expected": 0,
            "active": [],
            "source": "none",
            "ok": False,
        }

    hints = driver_ips(controller.driver) or list(config.bulb_ips)
    expected = max(len(config.bulb_ips), 1)
    found, source = await discovery.locate(hints)

    if found and sorted(found) != sorted(hints):
        try:
            new_config = replace(config, bulb_ips=tuple(found))
            await controller.swap_driver(build_driver(new_config))
            logger.warning(
                "light: 전구 IP가 바뀌었다 %s → %s. .env의 LIGHT_BULB_IP도 고쳐 두면 "
                "다음 부팅이 빨라진다.",
                ",".join(hints),
                ",".join(found),
            )
        except Exception:
            logger.warning("light: 찾은 전구로 갈아 끼우지 못했다", exc_info=True)

    active = found
    if not found:
        logger.warning(
            "light: 전구를 찾지 못했다 (적힌 IP %s). 핫스팟 연결·2.4GHz·전원을 확인하라.",
            ",".join(hints) or "없음",
        )
    else:
        logger.info("light: 전구 %d개 연결 (%s, %s)", len(found), ",".join(found), source)
    return {
        "driver": "yeelight",
        "expected": expected,
        "active": active,
        "source": source,
        "ok": len(active) >= expected,
    }
