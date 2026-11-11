"""로그만 남기는 드라이버. 개발 기본값."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from bulb.driver.base import RGB, LightDriver, SequenceStep

logger = logging.getLogger(__name__)


class MockDriver(LightDriver):
    """전구 없이 "무엇을 요청했는가"만 기록한다.

    테스트는 applied 목록을 단언하면 되므로 하드웨어 없이 연출 로직 전체를
    검증할 수 있다.
    """

    def __init__(self, sequence: bool = False) -> None:
        # 실물 전구처럼 시퀀스를 통째로 받을지. 기본은 끔 — 기존 테스트는
        # 단계별 apply() 기록을 단언한다.
        self.supports_sequence = sequence
        self.sequences: list[tuple[tuple[SequenceStep, ...], int]] = []
        self.alts: list[tuple[SequenceStep, ...] | None] = []
        self.applied: list[tuple[RGB, int, int]] = []
        # 색온도까지 본 기록. applied는 기존 단언들이 그대로 쓰도록 건드리지 않는다.
        self.calls: list[tuple[RGB, int, int, int | None]] = []
        self.closed = False

    async def apply(
        self,
        color: RGB,
        brightness: int,
        duration_ms: int,
        kelvin: int | None = None,
    ) -> None:
        self.applied.append((color, brightness, duration_ms))
        self.calls.append((color, brightness, duration_ms, kelvin))
        logger.debug(
            "light mock: rgb=%s brightness=%d duration=%dms kelvin=%s",
            color,
            brightness,
            duration_ms,
            kelvin,
        )

    async def play_sequence(
        self,
        steps: Sequence[SequenceStep],
        brightness: int,
        alt: Sequence[SequenceStep] | None = None,
    ) -> None:
        if not self.supports_sequence:
            raise NotImplementedError
        self.sequences.append((tuple(steps), brightness))
        self.alts.append(tuple(alt) if alt is not None else None)

    async def close(self) -> None:
        self.closed = True

    @property
    def last(self) -> tuple[RGB, int, int] | None:
        return self.applied[-1] if self.applied else None
