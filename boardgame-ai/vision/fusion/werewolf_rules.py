"""한밤의 늑대인간 전용 Fusion 규칙.

games/werewolf/ontology.py 직접 import 금지 — vision↔games 분리 규칙.
FSM 팀과 합의된 문자열 상수를 이 파일에서만 관리.

지원 이벤트:
  VOTE_POINT : 투표 페이즈에서 손목→검지 벡터로 좌석을 가리킴 감지

카드 인식(ROLE_DETECTED·CARD_PEEK·CARD_SWAP·CARD_PLACED_DOWN)은 인식률이 낮아
제거했다. 시스템은 플레이어의 역할을 알지 못하며, 야간 진행은 공용
GESTURE_CONFIRMED(OK 사인)로 처리한다 — 그쪽은 FusionEngine이 직접 담당하므로
이 모듈은 투표 포인팅만 책임진다.

감지 전략:
  VOTE_POINT → 손목[0]→검지끝[8] 방향 벡터 연장선에 가장 가까운 좌석을 지목으로 판정
"""

from __future__ import annotations

import math

from core.events import FusionContext
from vision.schemas import FramePerception, HandDet

# ── FSM 팀과 합의된 문자열 상수 ────────────────────────────────────────────────
# games/werewolf/ontology.py 의 WerewolfEventType / WerewolfPhase 와 동일한 값
VOTE_POINT = "werewolf_vote_point"

# FSM은 투표를 VOTE_COUNTDOWN("vote_countdown")으로 진입시키고 전원 투표 전까지
# 여기 머문다. "vote"는 자동 전이 경로가 없는 사실상 死페이즈이므로, 포인팅 투표는
# 두 문자열 모두에서 감지해야 한다. 둘 다 expected_events=[VOTE_POINT]로 동일 처리됨.
_PHASE_VOTE = "vote"
_PHASE_VOTE_COUNTDOWN = "vote_countdown"

# ── 감지 파라미터 ───────────────────────────────────────────────────────────────
_MIN_POINT_LENGTH = 0.03      # 손목→검지끝 최소 거리 (포인팅 제스처 판별)
_RAY_MAX_T = 1.5              # ray cast 최대 거리 (정규화)
# 투표: 손가락 ray 와 좌석 좌표 사이 허용 수직거리(정규화). 이 안에 들어오는
# 좌석 중 가장 가까운(ray 진행방향 t>0) 좌석을 지목 대상으로 본다.
_SEAT_POINT_PERP_DIST = 0.18


class WerewolfRules:
    """늑대인간 비전 이벤트 후보 생성기.

    FusionEngine 이 instantiate 하지 않고,
    WerewolfVisionPipeline 에서 생성해
    FusionEngine.register_werewolf_rules() 로 주입한다.
    """

    def __init__(self) -> None:
        self._last_phase: str = ""
        # VOTE_POINT: voter_id → 이미 투표한 target_id (1인 1표)
        self._votes_cast: dict[str, str] = {}

    def build_candidates(
        self,
        ctx: FusionContext,
        perception: FramePerception,
    ) -> list[tuple[str, dict, float]]:
        """FusionEngine.feed() 에서 호출.

        Returns
        -------
        list of (event_type, data_dict_with_key, confidence)
        """
        phase = ctx.fsm_state

        # 페이즈 전환 시 내부 상태 리셋 (중복 발화 방지 집합 초기화)
        if phase != self._last_phase:
            self._last_phase = phase
            self._votes_cast.clear()

        if phase not in (_PHASE_VOTE, _PHASE_VOTE_COUNTDOWN):
            return []

        candidates: list[tuple[str, dict, float]] = []
        for hand in perception.hands:
            c = self._check_vote_point(hand, ctx)
            if c:
                candidates.append(c)
        return candidates

    # ── VOTE_POINT ───────────────────────────────────────────────────────────────

    def _check_vote_point(
        self,
        hand: HandDet,
        ctx: FusionContext,
    ) -> tuple[str, dict, float] | None:
        """손목[0]→검지끝[8] ray 가 가장 잘 향하는 좌석(player)을 지목 → VOTE_POINT.

        ctx.anchors 의 seat_{pid} 좌표로 사람을 가리킨다. 1인 1표.
        """
        voter_id = hand.player_id
        if not voter_id:
            return None
        if not hand.landmarks_21 or len(hand.landmarks_21) < 9:
            return None

        wrist = hand.landmarks_21[0]      # landmark 0
        index_tip = hand.landmarks_21[8]  # landmark 8

        dx = index_tip[0] - wrist[0]
        dy = index_tip[1] - wrist[1]
        length = math.hypot(dx, dy)

        if length < _MIN_POINT_LENGTH:
            return None  # 검지가 접혀 있음

        nx, ny = dx / length, dy / length

        # ctx.anchors 에서 seat_{pid} 좌표 수집 (자기 자신 제외)
        best_target: str | None = None
        best_perp = _SEAT_POINT_PERP_DIST
        for key, pos in ctx.anchors.items():
            if not key.startswith("seat_"):
                continue
            target_id = key[len("seat_"):]
            if target_id == voter_id:
                continue
            sx = pos.get("x")
            sy = pos.get("y")
            if sx is None or sy is None:
                continue
            # ray(wrist + t·(nx,ny)) 위로의 좌석 투영 파라미터 t.
            t = (sx - wrist[0]) * nx + (sy - wrist[1]) * ny
            if t <= 0 or t > _RAY_MAX_T:
                continue  # 손가락 뒤쪽 또는 너무 먼 좌석
            # ray 직선과 좌석점 사이 수직거리.
            proj_x = wrist[0] + t * nx
            proj_y = wrist[1] + t * ny
            perp = math.hypot(sx - proj_x, sy - proj_y)
            if perp < best_perp:
                best_perp = perp
                best_target = target_id

        if best_target is None:
            return None

        # 동일 대상 매 프레임 재발화 억제. 대상이 바뀐 경우만 발화.
        if best_target == self._votes_cast.get(voter_id):
            return None

        self._votes_cast[voter_id] = best_target
        data = {
            "actor_id": voter_id,
            "target_id": best_target,
            "_key": (voter_id, best_target),
        }
        return VOTE_POINT, data, 0.85
