"""페르소나 말투 변환 결과 검사.

LLM이 말투를 바꾸다가 게임에 필요한 것까지 바꿔버리면 진행이 깨진다.
프롬프트로 아무리 당부해도 확률적이라, 결과를 확정적으로 검사한다.

변환은 페르소나를 고르는 시점에 한 번에 이뤄지므로 검사할 시간이 있다.
검사에 걸린 줄은 원문 그대로 쓴다 — 말투가 안 바뀐 문장 하나가 게임이
멈추는 것보다 낫다.

LLM이 필요 없다. 원문과 변환문 두 문자열만 비교한다.
"""

from __future__ import annotations

import re

# {player}, {score} 같은 슬롯. 하나라도 사라지면 이름·점수가 박제되어
# 다음 사람 차례에 엉뚱한 말이 나간다.
_SLOT = re.compile(r"\{(\w+)\}")

# 숫자. "카드 2장", "50점" 같은 것이 바뀌면 규칙 안내가 거짓말이 된다.
_NUMBER = re.compile(r"\d+")

# 영문 토큰. 요트 점수판 칸 이름(4 of a Kind, L. Straight)이 한국어로
# 번역되면 화면에서 그 칸을 못 찾는다.
_ASCII_WORD = re.compile(r"[A-Za-z]+")

# TTS가 그대로 읽어버리는 것들. "별표 별표 풀하우스"가 된다.
#
# 물결표 하나(~)는 뺐다. 마크다운 취소선은 두 개(~~)이고, 하나짜리는 한국어에서
# 말끝을 늘이는 표기다("천천히 햐유~"). 사투리·능청 말투에서 이걸 막으면
# 캐릭터의 절반이 날아간다. 두 개 이상만 잡는다.
_FORBIDDEN = re.compile(r"~~+|[*_#`\[\]<>|]|[\U0001F300-\U0001FAFF☀-➿]")

# 변환문이 원문보다 얼마나 길어져도 되는지. 말투를 바꾸면 어미가 늘어나므로
# 어느 정도는 허용하되, 설명을 덧붙이기 시작하면 낭독이 길어져 진행이 늘어진다.
_LENGTH_RATIO = 1.6
_LENGTH_SLACK = 12


def validate_line(original: str, converted: str) -> list[str]:
    """변환문의 문제 목록. 비어 있으면 통과.

    반환값은 사람이 읽는 사유 문자열이다 — 어떤 프롬프트 규칙을 강화해야
    하는지 리포트로 모으기 위한 것이다.
    """
    problems: list[str] = []

    # 원문이 비어 있는 항목이 있다(예: 튜토리얼은 부제를 쓰지 않는다).
    # 그건 "변환할 것이 없다"는 뜻이므로 빈 변환문이 정상이다.
    if not original.strip():
        return [] if not converted.strip() else ["원문이 빈 항목인데 문장이 생김"]

    if not converted.strip():
        return ["변환문이 비어 있음"]

    if "\n" in converted:
        problems.append("줄바꿈이 들어 있음")

    slots_before = set(_SLOT.findall(original))
    slots_after = set(_SLOT.findall(converted))
    if missing := slots_before - slots_after:
        problems.append(f"슬롯 유실: {', '.join(sorted(missing))}")
    if added := slots_after - slots_before:
        problems.append(f"없던 슬롯 추가: {', '.join(sorted(added))}")

    numbers_before = sorted(_NUMBER.findall(original))
    numbers_after = sorted(_NUMBER.findall(converted))
    if numbers_before != numbers_after:
        problems.append(f"숫자 바뀜: {numbers_before} → {numbers_after}")

    words_before = set(_ASCII_WORD.findall(original))
    words_after = set(_ASCII_WORD.findall(converted))
    if lost := words_before - words_after:
        problems.append(f"영문 표기 유실: {', '.join(sorted(lost))}")

    # 원문에 이미 있던 기호는 문제 삼지 않는다 — 개발용 "[개발]" 접두어처럼
    # 의도적으로 넣은 것이 있다. LLM이 **새로** 붙인 것만 잡는다.
    allowed = set(_FORBIDDEN.findall(original))
    if found := set(_FORBIDDEN.findall(converted)) - allowed:
        problems.append(f"읽히면 안 되는 문자: {''.join(sorted(found))}")

    limit = int(len(original) * _LENGTH_RATIO) + _LENGTH_SLACK
    if len(converted) > limit:
        problems.append(f"너무 길어짐: {len(converted)}자 (허용 {limit}자)")

    return problems


def validate_all(
    originals: dict[str, str],
    converted: dict[str, str],
) -> tuple[dict[str, str], dict[str, list[str]]]:
    """전체 변환 결과를 검사해 (쓸 것, 문제) 로 나눈다.

    - 검사를 통과한 줄만 쓴다. 걸린 줄은 결과에서 빼므로 원문으로 발화된다.
    - 원문에 없는 line_id는 무시한다 — 오타로 만든 항목이 조용히 섞이면
      나중에 왜 안 바뀌는지 찾기 어렵다.
    """
    accepted: dict[str, str] = {}
    rejected: dict[str, list[str]] = {}

    for line_id, text in converted.items():
        original = originals.get(line_id)
        if original is None:
            rejected[line_id] = ["원문에 없는 line_id"]
            continue
        problems = validate_line(original, text)
        if problems:
            rejected[line_id] = problems
        else:
            accepted[line_id] = text

    return accepted, rejected


def format_report(
    originals: dict[str, str],
    accepted: dict[str, str],
    rejected: dict[str, list[str]],
) -> str:
    """사람이 읽는 요약. 어떤 프롬프트 규칙을 강화해야 하는지 보이도록
    사유별로 묶는다."""
    lines = [
        f"원문 {len(originals)}줄 / 변환 성공 {len(accepted)} / 실패 {len(rejected)}",
    ]
    if not rejected:
        return "\n".join(lines)

    by_reason: dict[str, list[str]] = {}
    for line_id, problems in rejected.items():
        for problem in problems:
            # "슬롯 유실: player" → "슬롯 유실"로 묶는다
            key = problem.split(":")[0]
            by_reason.setdefault(key, []).append(line_id)

    lines.append("")
    for reason, ids in sorted(by_reason.items(), key=lambda kv: -len(kv[1])):
        lines.append(f"  {reason} {len(ids)}건")
        for line_id in sorted(ids)[:5]:
            lines.append(f"    - {line_id}: {rejected[line_id]}")
        if len(ids) > 5:
            lines.append(f"    ... 외 {len(ids) - 5}건")
    return "\n".join(lines)
