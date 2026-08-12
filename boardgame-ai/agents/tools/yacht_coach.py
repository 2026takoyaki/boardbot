"""요트 튜토리얼 코치 — 지금 나온 눈을 보고 무엇을 할 수 있는지 판단한다.

인트로 네 장으로 규칙은 설명했지만, 규칙을 안다고 첫 판을 굴릴 수 있는 건
아니다. 처음 하는 사람이 막히는 지점은 "룰을 모르겠다"가 아니라 눈 다섯 개를
앞에 두고 **이걸로 뭘 할 수 있는지 모르겠다** 쪽이다. 그래서 굴릴 때마다 그
눈에 대해서만 이야기한다.

원래 프론트(yachtCoach.js)에 있었으나 조언은 StrategyAgent의 일이라 백엔드로
옮겼다. 같은 판단이 프론트 JS와 백엔드 파이썬에 두 벌 있으면 한쪽만 고쳐지고,
무엇보다 프론트가 만든 문장에는 페르소나가 닿지 않는다.

여기서는 **문장을 만들지 않는다.** 어떤 조언을 할지(line_id)와 그 조언에 필요한
값만 정하고, 문장은 agents/tools/lines.py가 소유한다.

LLM을 부르지 않는다. 규칙 기반이라 네트워크가 죽어도 돌고, 무엇보다 틀린 조언을
하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from games.yacht.scoring import calculate_score

# 화면 점수판에 적힌 라벨. 조언이 "그 칸"을 가리키려면 화면과 같은 이름이어야
# 한다 — 한국어로 바꾸면 낭독은 자연스러워지지만 어느 칸인지 못 찾는다.
_LABEL: dict[str, str] = {
    "ones": "Aces",
    "twos": "Twos",
    "threes": "Threes",
    "fours": "Fours",
    "fives": "Fives",
    "sixes": "Sixes",
    "full_house": "Full House",
    "four_of_a_kind": "4 of a Kind",
    "small_straight": "S. Straight",
    "large_straight": "L. Straight",
    "yacht": "Yacht",
    "choice": "Choice",
}

# 낭독용 한글 이름. _LABEL과 용도가 다르다 —
#   _LABEL       "4 of a Kind"  화면의 그 칸을 가리켜야 할 때(코치)
#   KOREAN_LABEL "포카인드"      귀로만 듣는 훈수일 때(전략 조언), LLM 프롬프트 재료
# 화면을 보라고 하는 말이 아니면 한글이 낫다. "엘 스트레이트"로 읽히지 않는다.
KOREAN_LABEL: dict[str, str] = {
    "ones":           "1점짜리",
    "twos":           "2점짜리",
    "threes":         "3점짜리",
    "fours":          "4점짜리",
    "fives":          "5점짜리",
    "sixes":          "6점짜리",
    "choice":         "찬스",
    "four_of_a_kind": "포카인드",
    "full_house":     "풀하우스",
    "small_straight": "스몰스트레이트",
    "large_straight": "라지스트레이트",
    "yacht":          "요트",
}

_UPPER_KEY: tuple[str, ...] = ("ones", "twos", "threes", "fours", "fives", "sixes")

# 희귀한 것부터. 한 굴림이 여러 조합을 만족할 수 있어(요트는 포카드이기도 하다)
# 더 말할 값어치가 있는 쪽을 먼저 본다.
_HAND_ORDER: tuple[str, ...] = (
    "yacht", "large_straight", "four_of_a_kind", "full_house", "small_straight",
)

# 숫자를 읽었을 때 받침이 있는지. 일·삼·육은 있고 이·사·오는 없다.
# "5이 세 개"는 눈에 거슬리고, TTS로 읽히면 더 티가 난다.
_HAS_FINAL_CONSONANT = {1: True, 2: False, 3: True, 4: False, 5: False, 6: True}


def _with_josa(text: str, after_consonant: str, after_vowel: str) -> str:
    """마지막 숫자의 받침에 맞는 조사를 붙인다."""
    try:
        last = int(str(text)[-1])
    except (ValueError, IndexError):
        return f"{text}{after_vowel}"
    return f"{text}{after_consonant if _HAS_FINAL_CONSONANT.get(last) else after_vowel}"


def _score(category: str, values: list[int]) -> int:
    """점수 계산은 게임 규칙이 소유한다 — 코치가 따로 계산하면 두 벌이 된다.

    tuple로 넘기는 것은 타입 때문이다. calculate_score는 아직 읽히지 않은 눈까지
    받도록 list[int | None]을 받는데, 리스트는 불변이라 list[int]가 들어가지 않는다.
    여기까지 온 눈은 이미 온전하므로 공변인 tuple로 바꿔 넘긴다.
    """
    return calculate_score(category, tuple(values))


def _face_groups(dice: list[int]) -> list[tuple[int, int]]:
    """[눈, 개수] 목록. 개수 많은 순, 같으면 큰 눈 먼저.

    개수가 같을 때 큰 눈을 앞에 두는 것은 조언 때문이다 — 2가 둘, 5가 둘이면
    남길 값어치가 있는 쪽은 5다.
    """
    counts: dict[int, int] = {}
    for value in dice:
        counts[value] = counts.get(value, 0) + 1
    return sorted(counts.items(), key=lambda kv: (-kv[1], -kv[0]))


def _longest_run(dice: list[int]) -> list[int]:
    """가장 길게 이어진 눈들. [3,4,5]처럼 실제 값을 돌려준다."""
    best: list[int] = []
    current: list[int] = []
    for value in sorted(set(dice)):
        current = [*current, value] if current and value == current[-1] + 1 else [value]
        if len(current) > len(best):
            best = current
    return best


@dataclass(frozen=True)
class Advice:
    """조언 한 건. 문장이 아니라 무엇을 말할지의 목록이다.

    fragments의 각 (line_id, params)를 렌더해 공백으로 이어 붙이면 조언이 된다.
    조각으로 나누는 이유는 조건에 따라 뒷말이 붙었다 말았다 하기 때문이고,
    조각 하나하나가 완결된 문장이라 페르소나 변환도 조각 단위로 걸린다.
    """

    fragments: list[tuple[str, dict[str, object]]]
    key: str  # 같은 조언을 반복하지 않기 위한 식별자
    transient: bool = False  # True면 화면에서 잠시 후 사라진다
    extras: dict[str, object] = field(default_factory=dict)


def advice_key(
    phase: str,
    current_player: str | None,
    roll_count: int,
    dice: list[int],
) -> str | None:
    """지금 화면에 띄워야 할 조언의 식별자. 같으면 다시 말하지 않는다."""
    if phase == "AWAITING_ROLL":
        return "roll"
    if not dice:
        return None
    joined = "".join(str(v) for v in dice)
    return f"advice:{current_player}:{roll_count}:{joined}"


def advise(dice: list[int], available: list[str], roll_count: int) -> Advice | None:
    """굴린 눈에 대한 조언. 눈이 온전하지 않으면 None."""
    if len(dice) != 5 or any(v is None for v in dice):
        return None
    open_categories = [c for c in _LABEL if c in available]
    if not open_categories:
        return None

    values = [int(v) for v in dice]
    rolls_left = max(0, 3 - roll_count)
    key = f"advice:{roll_count}:{''.join(str(v) for v in values)}"

    ranked = sorted(
        ((c, _score(c, values)) for c in open_categories),
        key=lambda pair: pair[1],
        reverse=True,
    )
    best_key, best_score = ranked[0]

    completed = next(
        (c for c in _HAND_ORDER if c in open_categories and _score(c, values) > 0),
        None,
    )
    if completed:
        return Advice(_hand(completed, values, open_categories, rolls_left), key)
    if rolls_left == 0:
        return Advice(_last_call(best_key, best_score), key)
    return Advice(_keep(values, open_categories, best_key, best_score), key)


# ── 조합이 완성된 경우 ─────────────────────────────────────────────────────────


def _hand(
    category: str,
    values: list[int],
    open_categories: list[str],
    rolls_left: int,
) -> list[tuple[str, dict[str, object]]]:
    groups = _face_groups(values)
    run = _longest_run(values)
    score = _score(category, values)

    if category == "yacht":
        return [("coach.hand_yacht", {"face": values[0]})]

    if category == "large_straight":
        joined = "-".join(str(v) for v in run)
        return [("coach.hand_large_straight", {"run": _with_josa(joined, "으로", "로")})]

    if category == "four_of_a_kind":
        face = groups[0][0]
        out = [(
            "coach.hand_four_of_a_kind",
            {"face": _with_josa(str(face), "이", "가"), "score": score},
        )]
        # 하나만 더 맞추면 요트다. 아직 굴릴 기회가 있고 칸이 비었을 때만 권한다.
        if rolls_left > 0 and "yacht" in open_categories:
            out.append(("coach.hand_four_of_a_kind_chase", {"face": face}))
        return out

    if category == "full_house":
        return [(
            "coach.hand_full_house",
            {
                "triple": _with_josa(str(groups[0][0]), "이", "가"),
                "pair": _with_josa(str(groups[1][0]), "이", "가"),
                "score": score,
            },
        )]

    # small_straight
    joined = "-".join(str(v) for v in run)
    out = [("coach.hand_small_straight", {"run": _with_josa(joined, "이", "가")})]
    if rolls_left > 0 and "large_straight" in open_categories:
        out.append(("coach.hand_small_straight_chase", {}))
    return out


# ── 세 번을 다 굴린 경우 ───────────────────────────────────────────────────────


def best_category(dice: list[int], available: list[str]) -> tuple[str, int] | None:
    """지금 눈으로 가장 높은 점수가 나는 칸. 전략 조언(훈수)이 쓴다.

    코치는 "어떻게 굴릴까"까지 말하지만 훈수는 "어디에 넣을까"만 말한다.
    """
    if len(dice) != 5 or any(v is None for v in dice) or not available:
        return None
    values = [int(v) for v in dice]
    scored = [(c, _score(c, values)) for c in available if c in KOREAN_LABEL]
    if not scored:
        return None
    return max(scored, key=lambda pair: pair[1])


def _last_call(best_key: str, best_score: int) -> list[tuple[str, dict[str, object]]]:
    if best_score > 0:
        return [(
            "coach.last_call",
            {"label": _LABEL.get(best_key, best_key), "score": best_score},
        )]
    return [("coach.last_call_zero", {})]


# ── 아직 굴릴 기회가 남은 경우 ─────────────────────────────────────────────────


def _keep(
    values: list[int],
    open_categories: list[str],
    best_key: str,
    best_score: int,
) -> list[tuple[str, dict[str, object]]]:
    groups = _face_groups(values)
    top_face, top_count = groups[0]
    run = _longest_run(values)

    fallback: tuple[str, dict[str, object]] = (
        ("coach.fallback_best", {"label": _LABEL.get(best_key, best_key), "score": best_score})
        if best_score > 0
        else ("coach.fallback_none", {})
    )

    if top_count == 3:
        out: list[tuple[str, dict[str, object]]] = [(
            "coach.keep_triple",
            {"face": _with_josa(str(top_face), "이", "가")},
        )]
        # 같은 눈 셋은 상단 보너스로도 값어치가 있다. 그 칸이 비었을 때만.
        upper_key = _UPPER_KEY[top_face - 1]
        if upper_key in open_categories:
            out.append(("coach.keep_triple_bonus", {"label": _LABEL[upper_key]}))
        return out

    if len(run) == 3:
        joined = "-".join(str(v) for v in run)
        return [
            ("coach.keep_run", {"run": _with_josa(joined, "이", "가")}),
            fallback,
        ]

    if top_count == 2:
        return [
            ("coach.keep_pair", {"face": _with_josa(str(top_face), "이", "가")}),
            fallback,
        ]

    return [("coach.keep_none", {}), fallback]
