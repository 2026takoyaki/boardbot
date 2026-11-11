"""전구 여러 개를 하나처럼 다루는 드라이버.

전구 1개로는 테이블 전체가 충분히 밝지 않아 2개 이상을 함께 쓴다.
LightController는 뒤에 전구가 몇 개 물려 있는지 알 필요가 없다 — Scene/Cue
계산도, 밝기 하한도, 복귀 보장도 그대로다. 같은 명령을 모든 전구에 뿌리는
일만 여기서 한다.

**동시에** 보내는 것이 핵심이다. 순차로 보내면 전구 하나당 소켓 왕복이 세 번씩
일어나 두 전구의 페이드가 눈에 띄게 어긋난다. 늑대인간 새벽처럼 2.5초에 걸쳐
천천히 차오르는 연출에서는 그 어긋남이 그대로 보인다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable, Sequence

from bulb.driver.base import RGB, LightDriver, SequenceStep

logger = logging.getLogger(__name__)


class MultiDriver(LightDriver):
    """같은 명령을 여러 드라이버에 동시에 적용한다."""

    def __init__(self, drivers: Sequence[LightDriver]) -> None:
        if not drivers:
            raise ValueError("MultiDriver에는 드라이버가 최소 하나 필요하다.")
        self._drivers: tuple[LightDriver, ...] = tuple(drivers)

    def __len__(self) -> int:
        return len(self._drivers)

    async def apply(
        self,
        color: RGB,
        brightness: int,
        duration_ms: int,
        kelvin: int | None = None,
    ) -> None:
        await self._each(lambda d: d.apply(color, brightness, duration_ms, kelvin))

    @property
    def supports_sequence(self) -> bool:  # type: ignore[override]
        # 하나라도 못 받으면 전부 단계별 경로로 간다. 섞으면 전구마다 다른
        # 방식으로 움직여 색이 어긋난다.
        return all(d.supports_sequence for d in self._drivers)

    @property
    def drivers(self) -> tuple[LightDriver, ...]:
        return self._drivers

    async def play_sequence(
        self,
        steps: Sequence[SequenceStep],
        brightness: int,
        alt: Sequence[SequenceStep] | None = None,
    ) -> None:
        # 두 번째·네 번째 … 전구가 alt를 밟는다. 두 전구가 같은 박자로 서로
        # 다른 색·밝기를 내면 방 안에서 빛이 오가는 것처럼 보인다.
        plans = {
            id(d): (alt if alt is not None and i % 2 == 1 else steps)
            for i, d in enumerate(self._drivers)
        }
        await self._each(lambda d: d.play_sequence(plans[id(d)], brightness))

    async def _each(self, call: Callable[[LightDriver], Awaitable[None]]) -> None:
        results = await asyncio.gather(
            *(call(d) for d in self._drivers),
            return_exceptions=True,
        )

        failures: list[tuple[int, BaseException]] = []
        for index, result in enumerate(results):
            if not isinstance(result, BaseException):
                continue
            # 취소는 실패가 아니다. 그대로 올려보내야 LightController의 취소 경로
            # (캐시 무효화 후 재전송)가 돈다.
            if isinstance(result, asyncio.CancelledError):
                raise result
            failures.append((index, result))

        if not failures:
            return

        # 일부만 실패해도 예외를 올린다. 여기서 삼키면 LightController가 "전부
        # 보냈다"로 캐시하고, 다음에 같은 값이 오면 중복 제거로 걷어낸다. 그러면
        # 실패한 전구만 옛 색을 문 채 남는다 — 요트에서는 그대로 인식이 깨진다.
        # 성공한 전구에 같은 명령이 한 번 더 가는 것은 무해하다.
        detail = ", ".join(f"[{i}] {exc!r}" for i, exc in failures)
        raise RuntimeError(f"전구 {len(failures)}/{len(self._drivers)}개 적용 실패: {detail}")

    async def close(self) -> None:
        """전부 정리한다. 하나가 실패해도 나머지는 닫는다."""
        for driver in self._drivers:
            with contextlib.suppress(Exception):
                await driver.close()
