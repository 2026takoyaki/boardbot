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
from collections import Counter, deque

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

# 지목이 잡힌 최근 프레임을 이만큼 모아 두고, 그 안에서 같은 사람이
# _POINT_MIN_HITS 번 나오면 한 표로 친다.
#
# 왜 "연속 N프레임"이 아니라 창(window)인가:
#   팔을 드는 동안 손가락은 여러 좌석을 훑고 지나간다. 한 프레임만 보고 표를
#   매기면 스쳐 지나간 첫 좌석이 표가 되므로 얼마간 붙잡는 것을 요구해야 한다.
#   그런데 **연속**을 요구하면 이번엔 실제 시연에서 표가 아예 안 나온다 —
#   오버헤드 뷰에서 MediaPipe가 손을 프레임마다 놓쳤다 잡았다 하기 때문에
#   (실측 로그: 손이 30프레임 간격 샘플에서 나타났다 사라지길 반복) 연속 4프레임이
#   좀처럼 성립하지 않는다.
#
#   그래서 **지목이 잡힌 프레임만** 창에 넣는다. 손을 놓친 프레임은 창을 밀어내지
#   않으므로, 띄엄띄엄 잡혀도 겨누고 있는 한 표가 쌓인다. 스쳐 지나간 좌석은
#   한 번씩만 들어와 기준을 못 넘는다.
#
# 이 판정을 FusionEngine의 안정화 카운터에 맡길 수 없다. 아래 _votes_cast가
# 같은 대상의 후보 생성을 막기 때문에 카운터가 2 이상으로 오르지 못한다
# (그래서 FSM이 pointing_stabilization_frames를 1로 내려 쓰고 있다).
# 억제와 안정화가 같은 곳에 있어야 서로 어긋나지 않으므로 여기서 함께 센다.
_POINT_WINDOW = 8
_POINT_MIN_HITS = 3


class WerewolfRules:
    """늑대인간 비전 이벤트 후보 생성기.

    FusionEngine 이 instantiate 하지 않고,
    WerewolfVisionPipeline 에서 생성해
    FusionEngine.register_werewolf_rules() 로 주입한다.
    """

    def __init__(self) -> None:
        self._last_phase: str = ""
        # VOTE_POINT: voter_id → 마지막으로 발화한 target_id.
        # 같은 대상을 계속 가리키는 동안 매 프레임 재발화하지 않기 위한 것이지
        # "1인 1표"를 못박는 것이 아니다 — 카운트다운이 끝날 때까지 대상을 바꾸면
        # 몇 번이든 다시 발화한다. 최종 확정은 FSM의 votes_locked가 한다.
        self._votes_cast: dict[str, str] = {}
        # voter_id → 최근에 겨눈 좌석들. 지목이 잡힌 프레임만 들어간다.
        # 스쳐 지나간 좌석과 붙잡고 겨눈 좌석을 가른다.
        self._point_window: dict[str, deque[str]] = {}

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
            self._point_window.clear()

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

        ctx.anchors 의 seat_{pid} 좌표로 사람을 가리킨다.

        카운트다운이 끝날 때까지 지목은 몇 번이든 바뀔 수 있다. 대상을 바꿔
        _POINT_HOLD_FRAMES 만큼 붙잡으면 그때마다 새 VOTE_POINT가 나가고, FSM이
        그 값으로 덮어쓴다. 확정은 카운트다운이 끝나며 votes_locked가 한다.
        """
        voter_id = hand.player_id
        if not voter_id:
            return None
        if not hand.landmarks_21 or len(hand.landmarks_21) < 9:
            return self._break_streak(voter_id)

        wrist = hand.landmarks_21[0]      # landmark 0
        index_tip = hand.landmarks_21[8]  # landmark 8

        dx = index_tip[0] - wrist[0]
        dy = index_tip[1] - wrist[1]
        length = math.hypot(dx, dy)

        if length < _MIN_POINT_LENGTH:
            return self._break_streak(voter_id)  # 검지가 접혀 있음

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
            return self._break_streak(voter_id)

        # 최근에 겨눈 좌석들에 이번 프레임을 더한다. 팔을 드는 동안 스쳐 지나간
        # 좌석은 한 번씩만 들어와 기준을 못 넘는다.
        window = self._point_window.setdefault(voter_id, deque(maxlen=_POINT_WINDOW))
        window.append(best_target)
        counts = Counter(window)
        hits = counts[best_target]
        if hits < _POINT_MIN_HITS:
            return None
        # 창 안에서 지금 겨누는 쪽보다 더 많이 나온 좌석이 있으면 아직 그쪽이
        # 우세하다 — 마음을 바꾸는 중일 수 있으니 기다린다. 동률이면 지금
        # 겨누는 쪽이 이긴다: 같은 횟수라면 더 최근에 겨눈 쪽이 그 사람의 뜻이다.
        if any(t != best_target and c > hits for t, c in counts.items()):
            return None

        # 이미 이 대상으로 발화해 뒀으면 다시 보낼 것이 없다. 대상을 바꿔 그쪽이
        # 창에서 기준을 넘기면 그때 새로 나간다.
        if best_target == self._votes_cast.get(voter_id):
            return None

        self._votes_cast[voter_id] = best_target
        data = {
            "actor_id": voter_id,
            "target_id": best_target,
            "_key": (voter_id, best_target),
        }
        return VOTE_POINT, data, 0.85

    def _break_streak(self, voter_id: str) -> None:
        """지목이 안 잡힌 프레임.

        **창을 비우지 않는다.** 비우면 손을 한 번 놓칠 때마다 처음부터 세게 되고,
        오버헤드 뷰에서 손이 프레임마다 끊기는 실제 조건에서는 표가 영영 안 쌓인다.
        놓친 프레임은 그냥 아무것도 안 넣는 것으로 충분하다 — 겨누고 있는 한
        다음에 잡히는 프레임이 이어서 쌓인다.

        이미 발화한 표(_votes_cast)도 지우지 않는다. 손을 내렸다고 표가 사라지면
        카운트다운이 끝나는 순간 손을 들고 있던 사람만 투표한 것이 된다.
        """
        _ = voter_id
        return None
