"""조명 설정. 전부 환경변수로 조정 가능하고, 기본값은 하드웨어 없이 도는 값.

전구가 없어도, 전구가 죽어도 게임은 그대로 돌아야 한다. 그래서 기본 드라이버는
mock이고 실제 전구는 opt-in이다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# 게임별 밝기 하한. 전구 1개가 유일한 광원이라 이 값이 곧 정책이다.
#
#   yacht  — 이 전구가 곧 주사위 인식 조명이다. 어두워지면 YOLO가 못 읽는다.
#            연출보다 인식이 우선이므로 하한을 높게 잡는다 (설계문서 §4.7).
#   werewolf — 밤에는 비전이 할 일이 없다 (카드 인식 제거·손 투표 보류, §3.5).
#            완전 소등이 허용되고, 실제로 "밤이 되었습니다"는 암전에서 시작한다.
#   lobby  — 좌석 등록이 비전으로 돌아가는 구간이라 밝아야 한다 (§3.5).
#   control — 사람이 슬라이더로 직접 고른 값이다. 여기서 걷어올리면 고른 값과
#            실제 방이 어긋나고, 왜 안 어두워지는지 알 방법이 없다. 하한은
#            컨트롤 세션이 직접 갖는다(backend/control_session.py의 최소 5%).
_DEFAULT_FLOORS: dict[str, int] = {
    "yacht": 60,
    "werewolf": 0,
    "lobby": 60,
    "control": 0,
}

# 모르는 컨텍스트는 밝게 간다. 비전이 돌고 있을지 모르는데 어둡게 만드는 것보다
# 연출을 포기하는 쪽이 안전하다.
_FALLBACK_FLOOR = 60


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_ips(name: str) -> tuple[str, ...]:
    """쉼표로 나눈 IP 목록. 전구 1개면 값 하나만 적으면 된다.

    빈 항목은 버린다 — 끝에 쉼표가 붙거나 값이 통째로 비어 있어도 빈 IP로
    드라이버를 만들지 않는다.
    """
    raw = os.environ.get(name, "")
    return tuple(part.strip() for part in raw.split(",") if part.strip())


@dataclass(frozen=True)
class LightConfig:
    enabled: bool = True
    driver: str = "mock"
    # 전구는 여러 개일 수 있다. 1개로는 테이블이 충분히 밝지 않아 실제 시연은
    # 2개를 쓴다. 전부 같은 색·같은 밝기로 함께 움직인다 (bulb/driver/multi.py).
    bulb_ips: tuple[str, ...] = ()
    # 명령 하나가 이 시간을 넘기면 포기한다. 전구 응답 없음이 게임을 끌면 안 된다.
    command_timeout_s: float = 1.5
    brightness_floor: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_FLOORS))
    fallback_floor: int = _FALLBACK_FLOOR
    # 늑대인간 밤 밝기. 전구 1개가 유일한 광원이라 이 값 하나가 밤의 어둠을
    # 전적으로 결정한다. "어둡되 최소한 보이긴 해야 한다"는 지점은 실물로만
    # 찾을 수 있어 현장에서 LIGHT_NIGHT_BRIGHTNESS 로 조정한다 (§7.2-8).
    night_brightness: int = 15

    @classmethod
    def from_env(cls) -> LightConfig:
        floors = dict(_DEFAULT_FLOORS)
        for game in floors:
            floors[game] = _env_int(f"LIGHT_FLOOR_{game.upper()}", floors[game])
        return cls(
            enabled=_env_bool("LIGHT_ENABLED", True),
            driver=os.environ.get("LIGHT_DRIVER", "mock").strip().lower(),
            # LIGHT_BULB_IP=172.20.10.5           전구 1개
            # LIGHT_BULB_IP=172.20.10.5,172.20.10.6   전구 2개
            bulb_ips=_env_ips("LIGHT_BULB_IP"),
            command_timeout_s=_env_float("LIGHT_COMMAND_TIMEOUT", 1.5),
            brightness_floor=floors,
            fallback_floor=_env_int("LIGHT_FALLBACK_FLOOR", _FALLBACK_FLOOR),
            night_brightness=_env_int("LIGHT_NIGHT_BRIGHTNESS", 15),
        )

    def floor_for(self, game: str | None) -> int:
        """이 게임에서 허용되는 최저 밝기.

        늑대인간은 0(완전 소등)이고 요트는 인식 때문에 높다. 매핑 테이블이
        실수로 어두운 값을 넣어도 컨트롤러가 여기서 걷어낸다.
        """
        if game is None:
            return self.fallback_floor
        return self.brightness_floor.get(game, self.fallback_floor)
