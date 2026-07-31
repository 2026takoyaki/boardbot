"""로그만 남기는 드라이버. 개발 기본값."""

from __future__ import annotations

import logging

from bulb.driver.base import RGB, LightDriver

logger = logging.getLogger(__name__)


class MockDriver(LightDriver):
    """전구 없이 "무엇을 요청했는가"만 기록한다.

    테스트는 applied 목록을 단언하면 되므로 하드웨어 없이 연출 로직 전체를
    검증할 수 있다.
    """

    def __init__(self) -> None:
        self.applied: list[tuple[RGB, int, int]] = []
        self.closed = False

    async def apply(self, color: RGB, brightness: int, duration_ms: int) -> None:
        self.applied.append((color, brightness, duration_ms))
        logger.debug(
            "light mock: rgb=%s brightness=%d duration=%dms", color, brightness, duration_ms
        )

    async def close(self) -> None:
        self.closed = True

    @property
    def last(self) -> tuple[RGB, int, int] | None:
        return self.applied[-1] if self.applied else None
