"""개발 모드 — 카메라·전구 없이 두 게임을 손으로 굴려보기 위한 장치.

    BOARDBOT_DEV=1 uvicorn backend.server:app --port 8000

카메라가 없으면 좌석 등록을 통과할 수 없어 게임 자체를 시작할 수 없다. 연출을
조율하려면 매번 카메라 앞에 앉아 손을 흔들어야 했는데, 조명·모달·TTS 타이밍은
수십 번 돌려봐야 감이 잡히는 종류의 작업이라 그 비용이 크다.

**개발 입력은 프로덕션과 같은 경로로 흐른다.** 주사위는 비전이 만드는 것과
동일한 GameEvent를 주입하고, 좌석 등록도 실제 등록이 쓰는 SEAT_REGISTERED
이벤트를 그대로 쏜다. 지름길을 따로 파면 개발에서 되던 게 실전에서 안 되므로,
검증하는 대상이 실제로 도는 코드여야 한다.

모든 개발 입력은 is_dev_mode() 뒤에 있다. 플래그가 꺼져 있으면 입력 자체가
무시되므로 시연 중 실수로 눌릴 수 있는 경로가 남지 않는다.
"""

from __future__ import annotations

import math
import os
import random

from core.constants import CommonEventType
from core.events import GameEvent
from core.models import ArmAnchor, SeatZone

DEV_ENV_VAR = "BOARDBOT_DEV"


def is_dev_mode() -> bool:
    """개발 모드 여부. 프로세스 기동 시 환경변수로만 켜진다."""
    return os.environ.get(DEV_ENV_VAR, "").strip().lower() in ("1", "true", "yes", "on")


def synthetic_seat_zone(index: int, total: int) -> SeatZone:
    """테이블 둘레에 균등 배치한 가짜 좌석.

    실제 좌석은 MediaPipe가 양손 손목에서 측정하지만, 개발 모드에는 손이 없다.
    좌석 간 각도만 충분히 벌어져 있으면 좌석 매칭 로직이 서로를 구분하므로
    원 둘레에 등간격으로 놓는다.
    """
    total = max(1, total)
    angle = 2 * math.pi * index / total
    # 화면 중앙을 테이블 중심으로 보고 반지름 0.38 위치에 앉힌다.
    body_x = 0.5 + 0.38 * math.cos(angle)
    body_y = 0.5 + 0.38 * math.sin(angle)
    # 손은 몸에서 테이블 중심 쪽으로 조금 들어온 위치. 좌우로 벌려 놓는다.
    inward = angle + math.pi
    spread = 0.08
    right_x = body_x + 0.14 * math.cos(inward) + spread * math.cos(angle + math.pi / 2)
    right_y = body_y + 0.14 * math.sin(inward) + spread * math.sin(angle + math.pi / 2)
    left_x = body_x + 0.14 * math.cos(inward) - spread * math.cos(angle + math.pi / 2)
    left_y = body_y + 0.14 * math.sin(inward) - spread * math.sin(angle + math.pi / 2)

    return SeatZone(
        right_arm=ArmAnchor("Right", (right_x, right_y), inward),
        left_arm=ArmAnchor("Left", (left_x, left_y), inward),
        body_xy=(body_x, body_y),
        posture="stretched",
    )


def seat_registration_events(player_ids: list[str]) -> list[GameEvent]:
    """좌석 등록을 건너뛰기 위한 SEAT_REGISTERED 이벤트 묶음.

    실제 등록과 같은 이벤트라 orchestrator가 구분하지 못한다 — 플레이어 상태도,
    오디오 prewarm도, 조명도 전부 평소대로 돈다.
    """
    total = len(player_ids)
    return [
        GameEvent(
            event_type=CommonEventType.SEAT_REGISTERED.value,
            actor_id=player_id,
            confidence=1.0,
            frame_id=-1,
            data={"seat_zone": synthetic_seat_zone(index, total).to_dict()},
        )
        for index, player_id in enumerate(player_ids)
    ]


def roll_dice(keep_mask: list[bool] | None = None, previous: list[int] | None = None) -> list[int]:
    """개발용 주사위. keep_mask가 True인 자리는 이전 값을 유지한다."""
    previous = list(previous or [])
    keep_mask = list(keep_mask or [])
    values: list[int] = []
    for i in range(5):
        keep = i < len(keep_mask) and keep_mask[i] and i < len(previous)
        values.append(int(previous[i]) if keep else random.randint(1, 6))
    return values
