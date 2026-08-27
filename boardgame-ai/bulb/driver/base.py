"""조명 드라이버 인터페이스.

드라이버는 "이 색을 이 밝기로 켜라"만 안다. 어떤 페이즈인지, 왜 그 색인지,
꺼도 되는지는 LightController의 몫이다. 이 경계 덕분에 하드웨어 없이 연출
전체를 완성하고 검증할 수 있다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

RGB = tuple[int, int, int]

BRIGHTNESS_OFF = 0
BRIGHTNESS_MAX = 100

# 실물 전구(Yeelight color / color4)에서 측정한 색온도 지원 범위.
# 범위 밖 값은 전구가 조용히 걷어낸다 — 7000K를 보내면 6500K가 적용된다.
KELVIN_MIN = 1700
KELVIN_MAX = 6500


class LightDriver(ABC):
    """전구 한 개를 제어하는 최소 인터페이스.

    구현체는 apply()가 오래 걸리거나 실패할 수 있다고 가정해도 된다.
    타임아웃과 예외 처리는 LightController가 책임진다.
    """

    @abstractmethod
    async def apply(
        self,
        color: RGB,
        brightness: int,
        duration_ms: int,
        kelvin: int | None = None,
    ) -> None:
        """색·밝기를 duration_ms에 걸쳐 부드럽게 전환.

        Args:
            color: RGB 각 0~255. **이 색이 항상 의도다.** kelvin이 붙어도
                사라지지 않는다 — 화면에 조명을 그리는 드라이버는 이 값을 쓴다.
            kelvin: 흰색에 가까운 색을 낼 때의 색온도. 실물 전구는 RGB 세 다이를
                섞어 흰색을 만드는데, 다이별 광량 편차가 그대로 드러나 전구마다
                색이 갈린다 (실측: 같은 (255,225,190)을 받고 한쪽은 분홍, 한쪽은
                연두로 보였다). 색온도 모드는 전용 백색 LED를 쓰므로 개체 편차가
                훨씬 작고 더 밝다. None이면 color를 그대로 RGB로 낸다.
            brightness: 0~100. **0은 완전 소등이다.**
                늑대인간 밤 연출은 완전한 어둠에서 시작하므로 드라이버가
                소등을 막아서는 안 된다. 반대로 요트는 이 전구가 곧 인식
                조명이라 어두워지면 주사위를 못 읽는다. 그래서 하한은
                드라이버가 아니라 **게임별 정책**으로 두고 LightController가
                강제한다 (bulb/config.py의 brightness_floor).
            duration_ms: 전환에 쓸 시간. 0이면 즉시.
        """

    @abstractmethod
    async def close(self) -> None:
        """연결 정리. 여러 번 불려도 안전해야 한다."""
