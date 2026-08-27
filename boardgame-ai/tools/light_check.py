"""전구 현장 점검. 시연 전 1분 안에 끝난다.

    python -m tools.light_check                          # 환경변수의 IP 사용
    python -m tools.light_check 172.20.10.5              # 전구 1개
    python -m tools.light_check 172.20.10.5 172.20.10.6  # 전구 2개

전구가 여러 개면 먼저 하나씩 켜서 **어느 것이 안 붙는지** 알려주고, 그다음
전부 함께 연출 시퀀스를 돌린다. 실제 운영과 같은 경로(MultiDriver)를 쓰므로
여기서 통과하면 서버에서도 같게 움직인다.

IP를 모르면 (SSDP가 폰 핫스팟에서 동작한다는 보장이 없다):

    nmap -p 55443 --open 172.20.10.0/28

아이폰 핫스팟은 /28 서브넷이라 최대 14대다. 좁아서 전수 스캔이 1초면 끝난다.

전구가 안 잡히면 순서대로 확인한다.
    1. Mi Home 앱에서 "LAN 제어"가 켜져 있는가 — **기본이 꺼져 있다**
    2. 핫스팟이 2.4GHz인가 — 아이폰은 "호환성 최대화"를 켜야 한다
    3. 노트북과 전구가 같은 서브넷인가
"""

from __future__ import annotations

import asyncio
import logging
import sys

from bulb.config import LightConfig
from bulb.driver.base import LightDriver
from bulb.driver.multi import MultiDriver

logging.basicConfig(level=logging.INFO, format="%(message)s")

# (설명, RGB, 밝기, 전환시간)
_SEQUENCE: list[tuple[str, tuple[int, int, int], int, int]] = [
    ("중립 백색 최대 — 요트 주사위 인식 기준 밝기", (255, 255, 255), 100, 800),
    ("적색 어둡게 — 늑대인간 밤", (255, 30, 30), 15, 1200),
    ("따뜻한 백색 — 밤에서 낮으로(핵심 장면)", (255, 230, 200), 100, 2500),
    ("완전 소등 — 늑대인간 밤 시작", (0, 0, 0), 0, 2000),
    ("중립 백색 복귀", (255, 255, 255), 100, 800),
]


def _make_driver(ip: str) -> LightDriver:
    from bulb.driver.yeelight import YeelightDriver

    return YeelightDriver(ip)


async def _probe(ips: list[str]) -> list[str]:
    """하나씩 켜서 닿는 전구만 남긴다. 어느 것이 죽었는지 이름을 말해준다."""
    if len(ips) == 1:
        return ips

    print("전구별 연결 확인")
    alive: list[str] = []
    for ip in ips:
        print(f"  {ip} …", end=" ", flush=True)
        driver = _make_driver(ip)
        try:
            await asyncio.wait_for(driver.apply((255, 255, 255), 100, 300), timeout=5.0)
        except TimeoutError:
            print("타임아웃 — LAN 제어와 2.4GHz 연결을 확인하라")
        except Exception as exc:
            print(f"실패: {exc}")
        else:
            print("OK")
            alive.append(ip)
        finally:
            await driver.close()
    print()
    return alive


async def _run(ips: list[str]) -> int:
    try:
        _make_driver(ips[0])
    except ImportError:
        print("python-yeelight 미설치.  pip install yeelight")
        return 1

    alive = await _probe(ips)
    if not alive:
        print("연결된 전구가 없다. LAN 제어 활성화와 2.4GHz 연결을 확인하라.")
        return 1
    if len(alive) < len(ips):
        dead = [ip for ip in ips if ip not in alive]
        print(f"경고: {', '.join(dead)} 를 빼고 진행한다.\n")

    # 운영과 같은 경로. 전구 1개면 드라이버 하나, 여러 개면 MultiDriver.
    bulbs = [_make_driver(ip) for ip in alive]
    driver: LightDriver = bulbs[0] if len(bulbs) == 1 else MultiDriver(bulbs)
    print(f"연출 시퀀스 — 전구 {len(alive)}개 동시 제어\n")

    failures = 0
    for label, color, brightness, duration in _SEQUENCE:
        print(f"  {label} …", end=" ", flush=True)
        try:
            await asyncio.wait_for(driver.apply(color, brightness, duration), timeout=5.0)
        except TimeoutError:
            print("타임아웃")
            failures += 1
            continue
        except Exception as exc:
            print(f"실패: {exc}")
            failures += 1
            continue
        print("OK")
        # 눈으로 확인할 시간. 전환이 끝나고도 잠깐 머무른다.
        await asyncio.sleep(duration / 1000 + 1.0)

    await driver.close()

    if failures:
        print(f"\n{failures}개 실패. LAN 제어 활성화와 2.4GHz 연결을 확인하라.")
        return 1

    print(f"\n전부 통과. 조명 사용 가능 (전구 {len(alive)}개).")
    if len(alive) > 1:
        # 전구가 늘면 같은 밝기 값이 실제로는 더 밝다. 늑대인간 밤이 충분히
        # 어두웠는지는 위 시퀀스를 눈으로 보고 판단해야 한다.
        print("밤이 너무 밝았다면 LIGHT_NIGHT_BRIGHTNESS 를 낮춰서 다시 확인하라.")
    return 0


def main() -> int:
    ips = sys.argv[1:] or list(LightConfig.from_env().bulb_ips)
    if not ips:
        print(__doc__)
        print("IP를 인자로 주거나 LIGHT_BULB_IP 환경변수를 설정하라.")
        return 2
    return asyncio.run(_run(ips))


if __name__ == "__main__":
    raise SystemExit(main())
