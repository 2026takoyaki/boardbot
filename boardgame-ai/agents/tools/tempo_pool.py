"""템포 멘트 변형 풀 — 재촉하는 말을 게임이 시작되기 전에 미리 여러 개 만들어 둔다.

TempoAgent는 지연을 감당할 수 없는 유일한 에이전트다. "슬슬 정하셔야죠"가
3초 늦게 나오면 재촉이 아니라 뒷북이 된다. 그래서 여기만 LLM을 그 자리에서
부르지 않는다 — 페르소나가 정해지는 순간(게임 시작 전)에 변형을 만들어 TTS
캐시까지 데워 두고, 런타임에는 뽑아 쓰기만 한다. 발화 지연 0.

변형이 왜 필요한가:
    템포 멘트는 한 판에 수십 번 나온다. 같은 문장이 매번 똑같이 나오면
    진행자가 아니라 알람이 된다. 뜻은 같고 표현만 다른 문장 몇 개를 돌려
    쓰는 것만으로 그 인상이 크게 줄어든다.

실패해도 조용히 원문으로 돌아간다. 변형이 없다고 재촉을 못 하면 안 된다.
"""

from __future__ import annotations

import json
import logging
import random
from typing import Any

from agents.tools import lines, llm
from core.persona import Persona

logger = logging.getLogger(__name__)

# 변형을 만들 멘트. 전부 짧고 슬롯이 없어 통째로 캐시에 올릴 수 있는 것들이다.
POOL_LINE_IDS: tuple[str, ...] = (
    "tempo.half",
    "tempo.hurry",
    "tempo.almost",
    "tempo.close_eyes_again",
)

# 원문 포함 4~5개면 충분하다. 더 늘리면 prewarm 합성 시간만 길어지고,
# 사람은 어차피 한 판에 그 이상을 구분하지 못한다.
VARIANTS_PER_LINE = 3

# 재촉은 짧아야 재촉이다. 길면 말이 끝나기 전에 상황이 지나간다.
_MAX_LEN = 40

# 야간 마감 지시는 더 짧아야 한다.
#
# 이건 재촉이 아니라 단계를 닫는 지시라, 단계가 끝나기 전에 **반드시** 끝까지
# 나가야 한다. 남은 시간이 정해져 있으므로(TempoAgent.PHASE_END_WARNING_LEAD)
# 문장이 길면 그 안에 못 들어간다. 실제로 한 페르소나가 29자짜리 변형을 갖고
# 있었고, 그건 읽는 데만 6초라 눈을 감을 시간이 남지 않았다.
_MAX_LEN_BY_LINE: dict[str, int] = {
    "tempo.close_eyes_again": 16,
}

_pool: dict[str, list[str]] = {}
_last_pick: dict[str, str] = {}
_persona_id: str | None = None


def _prompt(persona: Persona) -> tuple[str, str]:
    style = f"{persona.style_prompt}\n\n" if persona.style_prompt else ""
    system = (
        style
        + "당신은 보드게임 진행자입니다. 주어진 재촉 멘트마다 뜻이 같고 표현만 다른 "
        f"문장을 {VARIANTS_PER_LINE}개씩 만드세요.\n"
        "- 말투와 인격은 위 지시를 그대로 따릅니다.\n"
        f"- 각 문장은 {_MAX_LEN}자 이내로 짧게. 재촉은 짧아야 재촉입니다.\n"
        f"- 단 '{'tempo.close_eyes_again'}'만은 {max_len('tempo.close_eyes_again')}자 이내. "
        "단계를 닫는 지시라 반드시 끝까지 나가야 합니다.\n"
        "- 중괄호, 이름, 숫자를 새로 넣지 마세요. 그대로 음성으로 읽힙니다.\n"
        '- 출력은 JSON 객체만: {"line_id": ["변형1", "변형2", ...]}'
    )
    user = "원문:\n" + json.dumps(
        {lid: lines.get(lid) or lines.original(lid) for lid in POOL_LINE_IDS},
        ensure_ascii=False,
        indent=2,
    )
    return system, user


def max_len(line_id: str) -> int:
    """이 멘트의 길이 상한. 야간 마감 지시만 더 짧다."""
    return _MAX_LEN_BY_LINE.get(line_id, _MAX_LEN)


def _accept(text: Any, line_id: str) -> str | None:
    """읽을 수 있는 문장만 통과시킨다. 슬롯이 남아 있으면 채워줄 사람이 없다."""
    if not isinstance(text, str):
        return None
    cleaned = llm.sanitize_for_tts(text)
    if not cleaned or "{" in cleaned or len(cleaned) > max_len(line_id):
        return None
    return cleaned


async def regenerate(persona: Persona, *, timeout: float | None = 20.0) -> list[str]:
    """페르소나에 맞는 변형을 새로 만든다. 미리 합성해 둘 문장 전체를 돌려준다.

    돌려준 목록을 AudioManager의 static 목록에 넣어야 캐시에 올라간다 —
    안 넣으면 변형이 나올 때마다 합성 지연이 붙어 안 만드느니만 못하다.
    """
    global _persona_id
    clear()
    _persona_id = persona.id

    # 원문(= 페르소나 말투가 적용된 고정 멘트)은 LLM과 무관하게 항상 들어간다.
    # 변형이 하나도 안 나와도 풀이 비지 않는다.
    for line_id in POOL_LINE_IDS:
        text = lines.get(line_id)
        if text:
            _pool[line_id] = [text]

    system, user = _prompt(persona)
    result = await llm.get_client().complete_json(
        system, user, max_tokens=600, timeout=timeout, tag="tempo.pool"
    )
    if not result.ok or not result.text:
        logger.info("[tempo] 변형 생성 건너뜀 — %s", result.error)
        return _all_texts()

    try:
        raw = json.loads(result.text)
    except json.JSONDecodeError:
        logger.warning("[tempo] JSON 파싱 실패, 원문만 사용")
        return _all_texts()

    added = 0
    for line_id in POOL_LINE_IDS:
        bucket = _pool.setdefault(line_id, [])
        for candidate in raw.get(line_id, []) if isinstance(raw, dict) else []:
            text = _accept(candidate, line_id)
            if text and text not in bucket:
                bucket.append(text)
                added += 1

    logger.info("[tempo] 변형 %d개 생성 (persona=%s)", added, persona.id)
    return _all_texts()


def _all_texts() -> list[str]:
    return [text for bucket in _pool.values() for text in bucket]


def pick(line_id: str) -> str | None:
    """이번에 말할 문장. 풀이 비어 있으면 고정 멘트로 떨어진다."""
    bucket = _pool.get(line_id)
    if not bucket:
        return lines.get(line_id)
    if len(bucket) == 1:
        return bucket[0]
    # 바로 앞에 쓴 문장은 피한다. 변형을 만들어 놓고 같은 걸 연속으로 뽑으면
    # 굳이 만든 값어치가 없다.
    choices = [t for t in bucket if t != _last_pick.get(line_id)] or bucket
    text = random.choice(choices)
    _last_pick[line_id] = text
    return text


def clear() -> None:
    global _persona_id
    _pool.clear()
    _last_pick.clear()
    _persona_id = None


def stats() -> dict[str, Any]:
    """디버그 엔드포인트용. 변형이 실제로 붙었는지 확인하는 창구."""
    return {
        "persona": _persona_id,
        "variants": {line_id: len(bucket) for line_id, bucket in _pool.items()},
    }
