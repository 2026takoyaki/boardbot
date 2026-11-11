"""전구 찾기. 적어 둔 IP가 안 맞으면 네트워크를 훑어 실제 IP를 찾는다.

핫스팟은 접속 순서에 따라 IP를 다르게 나눠줄 수 있다. 전구 IP를 .env에 고정해
두면, 어느 날 순서가 바뀌는 순간 조명이 조용히 죽는다 — 서버는 조명이 없어도
멀쩡히 뜨도록 만들어져 있어서 화면만 봐서는 알 수 없다. 그래서 적힌 IP는
**힌트**로만 쓰고, 안 닿으면 직접 찾는다.

찾는 방법은 둘이다. 둘 다 2026-11-11 아이폰 핫스팟에서 동작을 확인했다.

    SSDP   전구가 스스로 대답한다(멀티캐스트). 빠르고 모델까지 알려준다.
    포트   Yeelight 제어 포트(55443)가 열린 기기를 찾는다. 멀티캐스트를
           막는 네트워크에서도 된다. 핫스팟은 /28(14대)이라 순식간이다.

찾은 기기가 우리 전구인지는 따로 확인하지 않는다. 시연 핫스팟에 55443을 연
다른 기기가 있을 리 없고, 확인하려면 명령을 보내야 하는데 그건 분당 명령
예산을 쓴다.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import logging
import socket
from collections.abc import Iterable, Sequence

logger = logging.getLogger(__name__)

YEELIGHT_PORT = 55443

# 포트 하나 두드리는 데 쓰는 시간. 같은 망의 기기는 수 ms 안에 대답한다.
_PROBE_TIMEOUT_S = 0.6

# 이보다 넓은 망은 훑지 않는다. 학교·행사장 와이파이(/16, /19 …)를 통째로
# 두드리면 오래 걸리고 보안 장비에 걸릴 수도 있다. 시연은 핫스팟(/28)이다.
_MAX_SCAN_HOSTS = 254


async def probe(ip: str, timeout: float = _PROBE_TIMEOUT_S) -> bool:
    """ip의 제어 포트가 열려 있는가. 명령은 보내지 않는다(명령 예산을 안 쓴다)."""
    try:
        _reader, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, YEELIGHT_PORT), timeout=timeout
        )
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def probe_all(ips: Iterable[str]) -> list[str]:
    """닿는 것만 남긴다. 순서는 입력 순서를 따른다."""
    targets = list(dict.fromkeys(ips))
    results = await asyncio.gather(*(probe(ip) for ip in targets))
    return [ip for ip, ok in zip(targets, results, strict=True) if ok]


def _local_networks() -> list[ipaddress.IPv4Network]:
    """노트북이 지금 붙어 있는 망. 기본 경로의 인터페이스 하나만 본다.

    넷마스크를 알 방법이 표준 라이브러리에 없어서 /24로 잡는다. 아이폰
    핫스팟(/28)은 그 안에 들어간다.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            # UDP connect는 패킷을 보내지 않는다. 어느 인터페이스로 나갈지만 정한다.
            s.connect(("192.0.2.1", 9))
            local_ip = s.getsockname()[0]
    except OSError:
        return []
    if local_ip.startswith("127."):
        return []
    return [ipaddress.ip_network(f"{local_ip}/24", strict=False)]


def _networks_for(hints: Sequence[str]) -> list[ipaddress.IPv4Network]:
    nets: list[ipaddress.IPv4Network] = []
    for ip in hints:
        try:
            nets.append(ipaddress.ip_network(f"{ip}/24", strict=False))
        except ValueError:
            continue
    nets.extend(_local_networks())
    return list(dict.fromkeys(nets))


async def scan(hints: Sequence[str] = ()) -> list[str]:
    """제어 포트가 열린 기기를 찾는다. 적힌 IP의 /24와 노트북의 /24를 훑는다."""
    hosts: list[str] = []
    for net in _networks_for(hints):
        if net.num_addresses - 2 > _MAX_SCAN_HOSTS:
            continue
        hosts.extend(str(h) for h in net.hosts())
    if not hosts:
        return []
    return await probe_all(hosts)


def _ssdp_sync(timeout: float) -> list[str]:
    try:
        from yeelight import discover_bulbs
    except ImportError:
        return []
    try:
        return [b["ip"] for b in discover_bulbs(timeout=timeout) if "ip" in b]
    except Exception:
        logger.debug("light: SSDP 탐색 실패", exc_info=True)
        return []


async def ssdp(timeout: float = 2.0) -> list[str]:
    return await asyncio.to_thread(_ssdp_sync, timeout)


def _ip_key(ip: str) -> tuple[int, ...]:
    try:
        return tuple(ipaddress.ip_address(ip).packed)
    except ValueError:
        return (999,)


async def locate(configured: Sequence[str]) -> tuple[list[str], str]:
    """실제로 닿는 전구 IP 목록과 그것을 어떻게 얻었는지.

    적힌 IP가 전부 닿으면 그대로 쓴다(가장 흔한 경우, 1초 안에 끝난다).
    하나라도 안 닿으면 SSDP와 포트 스캔을 함께 돌려 찾은 것을 전부 쓴다.
    아무것도 못 찾으면 빈 목록이다 — 그때는 호출자가 적힌 IP를 그대로 두고
    전구가 늦게 붙기를 기다린다.

    Returns:
        (IP 목록, "configured" | "discovered" | "none")
    """
    alive = await probe_all(configured)
    if configured and len(alive) == len(configured):
        return list(configured), "configured"

    via_ssdp, via_scan = await asyncio.gather(ssdp(), scan(configured))
    found = sorted(set(alive) | set(via_ssdp) | set(via_scan), key=_ip_key)
    if not found:
        return [], "none"
    return found, "discovered"
