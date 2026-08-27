"""MultiDriver 검증. 전구 여러 개를 하나처럼 다루는 계약을 지키는지 본다."""

from __future__ import annotations

import asyncio

import pytest

from bulb import build_driver
from bulb.config import LightConfig
from bulb.driver.base import RGB, LightDriver
from bulb.driver.mock import MockDriver
from bulb.driver.multi import MultiDriver

WARM = (255, 230, 200)


class _FailingDriver(LightDriver):
    """항상 실패하는 전구. 한 개가 죽었을 때의 동작을 보기 위한 것."""

    def __init__(self) -> None:
        self.closed = False

    async def apply(self, color: RGB, brightness: int, duration_ms: int) -> None:
        raise OSError("전구 응답 없음")

    async def close(self) -> None:
        self.closed = True


class _SlowDriver(MockDriver):
    """적용에 시간이 걸리는 전구. 동시 실행 여부를 재기 위한 것."""

    def __init__(self, delay: float) -> None:
        super().__init__()
        self._delay = delay

    async def apply(self, color: RGB, brightness: int, duration_ms: int) -> None:
        await asyncio.sleep(self._delay)
        await super().apply(color, brightness, duration_ms)


@pytest.mark.asyncio
async def test_같은_명령이_모든_전구에_간다() -> None:
    a, b = MockDriver(), MockDriver()

    await MultiDriver([a, b]).apply(WARM, 100, 2500)

    assert a.applied == [(WARM, 100, 2500)]
    assert b.applied == [(WARM, 100, 2500)]


@pytest.mark.asyncio
async def test_전구들이_동시에_움직인다() -> None:
    """순차로 보내면 두 전구의 페이드가 눈에 띄게 어긋난다."""
    delay = 0.05
    drivers = [_SlowDriver(delay) for _ in range(3)]

    start = asyncio.get_running_loop().time()
    await MultiDriver(drivers).apply(WARM, 100, 800)
    elapsed = asyncio.get_running_loop().time() - start

    # 순차라면 delay * 3. 동시라면 delay 한 번. 절반 아래면 확실히 동시다.
    assert elapsed < delay * len(drivers) / 2


@pytest.mark.asyncio
async def test_한_전구가_실패해도_나머지는_적용된다() -> None:
    alive, dead = MockDriver(), _FailingDriver()

    with pytest.raises(RuntimeError):
        await MultiDriver([alive, dead]).apply(WARM, 100, 800)

    assert alive.applied == [(WARM, 100, 800)]


@pytest.mark.asyncio
async def test_일부_실패는_예외로_올라온다() -> None:
    """삼키면 LightController가 '전부 보냈다'로 캐시해 실패한 전구만 옛 색에 남는다.

    요트에서는 그 상태로 다음 굴림이 들어와 인식이 깨진다. 예외를 올려야
    컨트롤러가 캐시를 비우고 다음 명령을 다시 보낸다.
    """
    driver = MultiDriver([MockDriver(), _FailingDriver()])

    with pytest.raises(RuntimeError, match="1/2"):
        await driver.apply(WARM, 100, 800)


@pytest.mark.asyncio
async def test_전부_성공하면_조용하다() -> None:
    driver = MultiDriver([MockDriver(), MockDriver()])
    await driver.apply(WARM, 100, 800)  # 예외 없음


@pytest.mark.asyncio
async def test_close는_하나가_실패해도_전부_닫는다() -> None:
    a, dead, b = MockDriver(), _FailingDriver(), MockDriver()

    await MultiDriver([a, dead, b]).close()

    assert a.closed and b.closed and dead.closed


def test_빈_목록은_거부한다() -> None:
    with pytest.raises(ValueError):
        MultiDriver([])


# ── 조립 ──────────────────────────────────────────────────────────────────────


def test_IP가_하나면_전구를_직접_쓴다(monkeypatch: pytest.MonkeyPatch) -> None:
    """굳이 감싸지 않는다. 전구 1개 구성이 계속 지금과 같게 동작해야 한다."""
    pytest.importorskip("yeelight")
    monkeypatch.setenv("LIGHT_DRIVER", "yeelight")
    monkeypatch.setenv("LIGHT_BULB_IP", "172.20.10.5")

    driver = build_driver(LightConfig.from_env())

    assert not isinstance(driver, MultiDriver)


def test_IP가_여럿이면_묶는다(monkeypatch: pytest.MonkeyPatch) -> None:
    pytest.importorskip("yeelight")
    monkeypatch.setenv("LIGHT_DRIVER", "yeelight")
    monkeypatch.setenv("LIGHT_BULB_IP", "172.20.10.5,172.20.10.6")

    driver = build_driver(LightConfig.from_env())

    assert isinstance(driver, MultiDriver)
    assert len(driver) == 2


def test_공백과_빈_항목은_버린다(monkeypatch: pytest.MonkeyPatch) -> None:
    """끝에 쉼표가 붙어도 빈 IP로 드라이버를 만들지 않는다."""
    monkeypatch.setenv("LIGHT_BULB_IP", " 172.20.10.5 , ,172.20.10.6, ")

    assert LightConfig.from_env().bulb_ips == ("172.20.10.5", "172.20.10.6")


def test_IP가_없으면_빈_목록이다(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LIGHT_BULB_IP", raising=False)

    assert LightConfig.from_env().bulb_ips == ()
