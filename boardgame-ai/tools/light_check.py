"""전구 현장 점검. 시연 전 30초 안에 끝난다.

    python -m tools.light_check                  # 환경변수의 IP 사용
    python -m tools.light_check 172.20.10.5      # IP 직접 지정

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
import os
import sys

from bulb.config import LightConfig
from bulb.driver.base import LightDriver

logging.basicConfig(level=logging.INFO, format="%(message)s")

# (설명, RGB, 밝기, 전환시간)
_SEQUENCE: list[tuple[str, tuple[int, int, int], int, int]] = [
    ("중립 백색 최대 — 요트 주사위 인식 기준 밝기", (255, 255, 255), 100, 800),
    ("적색 어둡게 — 늑대인간 밤", (255, 30, 30), 15, 1200),
    ("따뜻한 백색 — 밤에서 낮으로(핵심 장면)", (255, 230, 200), 100, 2500),
    ("완전 소등 — 늑대인간 밤 시작", (0, 0, 0), 0, 2000),
    ("중립 백색 복귀", (255, 255, 255), 100, 800),
]


async def _run(ip: str) -> int:
    try:
        from bulb.driver.yeelight import YeelightDriver
    except ImportError:
        print("python-yeelight 미설치.  pip install yeelight")
        return 1

    driver: LightDriver = YeelightDriver(ip)
    print(f"전구 {ip} 점검 시작\n")

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
    print("\n전부 통과. 조명 사용 가능.")
    return 0


def main() -> int:
    ip = sys.argv[1] if len(sys.argv) > 1 else (LightConfig.from_env().bulb_ip or "")
    if not ip:
        print(__doc__)
        print("IP를 인자로 주거나 LIGHT_BULB_IP 환경변수를 설정하라.")
        return 2
    os.environ.setdefault("LIGHT_BULB_IP", ip)
    return asyncio.run(_run(ip))


if __name__ == "__main__":
    raise SystemExit(main())
