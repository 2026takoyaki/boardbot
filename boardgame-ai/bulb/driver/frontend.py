"""화면으로 조명을 대신 보여주는 드라이버.

두 가지 역할을 겸한다.

1. **개발 시각화** — 전구가 없어도 연출을 눈으로 확인하며 만들 수 있다.
2. **폴백** — 시연 당일 전구가 안 붙어도 화면으로 분위기를 대체한다.
   단일 광원 전제라 물리 조명이 죽으면 요트 인식까지 멈추지만(그건 천장등
   수동 점등으로 대응한다), 최소한 연출 의도는 보여줄 수 있다.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

from bulb.driver.base import RGB, LightDriver

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[dict[str, Any]], Awaitable[None] | None]


class FrontendDriver(LightDriver):
    """조명 상태를 WS 메시지로 프론트에 넘긴다.

    프론트는 이 값으로 화면 가장자리에 색 띠를 그린다. 실제 전구와 같은
    (color, brightness, duration) 을 받으므로 둘이 자동으로 동기화된다.
    """

    def __init__(self, broadcast: BroadcastFn) -> None:
        self._broadcast = broadcast

    async def apply(self, color: RGB, brightness: int, duration_ms: int) -> None:
        result = self._broadcast(
            {
                "msg_type": "light_state",
                "payload": {
                    "color": list(color),
                    "brightness": brightness,
                    "duration_ms": duration_ms,
                },
            }
        )
        if result is not None:
            await result

    async def close(self) -> None:
        return None
