"""조명 드라이버 인터페이스.

드라이버는 "이 색을 이 밝기로 켜라"만 안다. 어떤 페이즈인지, 왜 그 색인지,
꺼도 되는지는 LightController의 몫이다. 이 경계 덕분에 하드웨어 없이 연출
전체를 완성하고 검증할 수 있다.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass

RGB = tuple[int, int, int]

BRIGHTNESS_OFF = 0
BRIGHTNESS_MAX = 100

# 실물 전구(Yeelight color / color4)에서 측정한 색온도 지원 범위.
# 범위 밖 값은 전구가 조용히 걷어낸다 — 7000K를 보내면 6500K가 적용된다.
KELVIN_MIN = 1700
KELVIN_MAX = 6500


@dataclass(frozen=True)
class SequenceStep:
    """색 여러 개를 밟는 연출의 한 단계.

    hold_ms는 이 색이 차지하는 전체 시간이고 그 앞부분 transition_ms 동안
    직전 색에서 넘어온다. 둘이 같으면 색이 멈추지 않고 계속 흘러간다(무지개).
    """

    color: RGB
    hold_ms: int
    transition_ms: int
    # None이면 시퀀스 전체 밝기를 쓴다. 반짝임처럼 밝기가 오르내리는 연출만 단다.
    brightness: int | None = None


# 흐름 한 단계의 최소 길이. 그 아래는 전구가 명령을 거부한다.
MIN_FLOW_STEP_MS = 50


def flow_transition_count(step: SequenceStep) -> int:
    """이 단계가 흐름에서 차지하는 전환 수 — 넘어가기 하나, 머무르기 하나."""
    fade = max(MIN_FLOW_STEP_MS, min(step.transition_ms, step.hold_ms))
    return 1 + (1 if step.hold_ms - fade >= MIN_FLOW_STEP_MS else 0)


# 흐름(color flow) 하나에 실을 수 있는 전환 수. 실물에서 16개는 받고 24개는
# 거부했다(invalid command, 2026-11-11 Yeelight color fw 65). 경계를 정확히
# 찾지 않고 확인된 값에서 멈춘다.
MAX_FLOW_TRANSITIONS = 16


def flow_period(steps: Sequence[SequenceStep]) -> tuple[tuple[SequenceStep, ...], int]:
    """steps를 (한 바퀴, 반복 횟수)로 접는다.

    전구는 흐름 하나에 전환을 16개 남짓밖에 못 받지만, 같은 흐름을 몇 번
    반복할지는 따로 받는다. 파티(6색 × 4바퀴)나 무지개(7색 × 2바퀴)처럼 같은
    패턴을 도는 연출은 한 바퀴만 보내면 된다. 반복이 아니면 통째로 한 바퀴다.
    """
    items = tuple(steps)
    n = len(items)
    for size in range(1, n + 1):
        if n % size == 0 and items == items[:size] * (n // size):
            return items[:size], n // size
    return items, 1


def plan_flows(
    steps: Sequence[SequenceStep],
    alt: Sequence[SequenceStep] | None = None,
) -> list[tuple[int, tuple[SequenceStep, ...], tuple[SequenceStep, ...] | None]]:
    """시퀀스를 전구에 보낼 묶음으로 나눈다. [(시작 ms, 단계들, 짝 전구 단계들)].

    반복 패턴으로 접어서 한 흐름에 들어가면 묶음은 하나다(파티·반짝임). 안
    들어가면 앞에서부터 전환 16개씩 끊는다 — 피날레처럼 효과음 박자에 맞춘
    연출은 반복이 아니라서 길다. 묶음마다 명령이 하나씩이라 몇 개로 나뉘어도
    분당 명령 제한과는 거리가 멀다.

    alt는 짝수 번째가 아닌 전구(두 번째 전구)가 대신 밟을 단계다. 박자가
    같아야 하므로 단계 수와 길이가 steps와 같아야 한다 — 색과 밝기만 다르다.
    """
    items = tuple(steps)
    pair = tuple(alt) if alt is not None else None
    if pair is not None and [(s.hold_ms, s.transition_ms) for s in pair] != [
        (s.hold_ms, s.transition_ms) for s in items
    ]:
        raise ValueError("짝 전구 단계는 박자(길이·전환)가 같아야 한다")

    def fits(seq: tuple[SequenceStep, ...]) -> bool:
        period, _ = flow_period(seq)
        return sum(flow_transition_count(s) for s in period) <= MAX_FLOW_TRANSITIONS

    if fits(items) and (pair is None or fits(pair)):
        return [(0, items, pair)]

    plans: list[tuple[int, tuple[SequenceStep, ...], tuple[SequenceStep, ...] | None]] = []
    start = 0
    offset = 0
    used = 0
    for index, step in enumerate(items):
        cost = flow_transition_count(step)
        if used + cost > MAX_FLOW_TRANSITIONS and index > start:
            plans.append((offset, items[start:index], pair[start:index] if pair else None))
            offset += sum(s.hold_ms for s in items[start:index])
            start, used = index, 0
        used += cost
    plans.append((offset, items[start:], pair[start:] if pair else None))
    return plans


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

    # ── 색 시퀀스 (선택 기능) ────────────────────────────────────────────────
    #
    # 실물 전구에는 분당 명령 수 제한이 있다(Yeelight 약 60개). 색이 여러 번
    # 바뀌는 연출을 apply() 반복으로 보내면 그 한 번으로 제한을 넘기고, 넘긴
    # 뒤에는 **복귀 명령까지 거부돼** 마지막 색에 멈춘다 (2026-11-11 실측:
    # 파티 큐 한 번 → client quota exceeded → 분홍색에 고정).
    #
    # 전구가 시퀀스를 통째로 받을 수 있으면 명령 하나로 끝난다. 그런 드라이버만
    # supports_sequence를 켠다. 나머지는 LightController가 apply()를 단계마다
    # 부르는 기존 경로로 돈다 — 화면에 조명을 그리는 드라이버는 그쪽이 맞다.

    supports_sequence: bool = False

    async def play_sequence(
        self,
        steps: Sequence[SequenceStep],
        brightness: int,
        alt: Sequence[SequenceStep] | None = None,
    ) -> None:
        """steps를 차례로 밟는 연출을 **시작**하고 곧바로 반환한다.

        alt는 여러 전구를 묶은 드라이버에서 두 번째 전구가 대신 밟는 단계다
        (두 전구가 엇갈려 반짝이는 연출). 전구 하나짜리 드라이버는 무시한다.

        끝까지 기다리지 않는다. 진행은 전구가 스스로 하고, 끝나면 마지막 색에
        머문다. 언제 끝나는지는 steps가 알고 있으므로 호출자가 잰다.
        """
        raise NotImplementedError
