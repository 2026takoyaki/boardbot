"""Scene · Cue 정의.

조명 연출에는 성격이 다른 두 종류가 있다.

    Scene — 페이즈가 유지되는 동안의 바탕 조명. 수명이 페이즈와 같다.
    Cue   — 순간적으로 터지고 Scene으로 돌아온다. 0.5~3초.

Cue의 계약: **반드시 Scene으로 복귀하며 끝난다.** 이 규칙이 있어야 조명이
이상한 상태로 멈춰 요트 주사위 인식을 망치는 사고를 구조적으로 막을 수 있다.

게임별 매핑 테이블은 이 모듈이 아니라 후속 작업에서 채운다. 여기서는 타입과
어디서나 안전한 기본값만 정의한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from bulb.driver.base import RGB

NEUTRAL_WHITE: RGB = (255, 255, 255)


@dataclass(frozen=True)
class Scene:
    """페이즈가 유지되는 동안의 바탕 조명."""

    name: str
    color: RGB
    brightness: int
    transition_ms: int = 1200

    @property
    def is_blackout(self) -> bool:
        return self.brightness <= 0


@dataclass(frozen=True)
class Cue:
    """터지고 Scene으로 돌아오는 순간 연출.

    rise → hold → fall 세 구간으로 쪼갠 이유는 복귀 페이드(fall)를 길이 계산에
    반드시 포함시키기 위해서다. 복귀가 끝나는 시점이 곧 "다음 굴림을 인식해도
    안전한 시점"이라, 이 값이 모달 지속시간과 맞물린다.
    """

    name: str
    color: RGB
    brightness: int
    rise_ms: int
    hold_ms: int
    fall_ms: int

    @property
    def total_ms(self) -> int:
        """복귀 페이드까지 포함한 전체 길이."""
        return self.rise_ms + self.hold_ms + self.fall_ms

    def fits_within(self, duration_ms: int) -> bool:
        """모달이 닫히기 전에 조명이 Scene으로 돌아와 있는가.

        설계문서 §2.4의 불변식: 모달 duration >= Cue 전체 길이.
        요트에서 이걸 어기면 모달이 사라진 뒤에도 조명이 아직 색을 물고 있고,
        그 상태로 다음 굴림이 들어와 인식이 깨진다.
        """
        return self.total_ms <= duration_ms


# 어디서 쓰든 안전한 바탕. 인식이 필요한 구간(요트 전 구간, 로비 좌석 등록)의
# 기본값이자, 매핑에 없는 페이즈를 만났을 때의 폴백이다.
NEUTRAL_SCENE = Scene(
    name="neutral",
    color=NEUTRAL_WHITE,
    brightness=100,
    transition_ms=800,
)

# 완전한 어둠. 늑대인간 "밤이 되었습니다" 구간처럼 비전이 유휴일 때만 쓴다.
# 요트에서 이 Scene이 요청되면 밝기 하한에 걸려 자동으로 걷어내진다.
BLACKOUT_SCENE = Scene(
    name="blackout",
    color=NEUTRAL_WHITE,
    brightness=0,
    transition_ms=2000,
)
