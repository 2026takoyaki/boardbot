"""고정 멘트를 페르소나 말투로 일괄 변환한다.

발화할 때마다 LLM을 부르지 않는다. 매 페이즈에 생성+합성 지연이 겹치면
진행이 끊긴다. 페르소나를 고르는 시점에 한 번에 바꿔 파일로 갖고 있다가
런타임에는 읽기만 한다.

    python tools/generate_persona_lines.py granny
    python tools/generate_persona_lines.py granny --dry-run   # 프롬프트만 확인
    python tools/generate_persona_lines.py --all              # 빠진 줄만 채움
    python tools/generate_persona_lines.py --all --force      # 전부 새로 뽑음

기본은 **증분**이다. 이미 변환된 줄은 건드리지 않고 lines.py에 새로 생긴
줄만 채운다. 전부 다시 뽑으면 귀로 확인하고 통과시킨 문장까지 같이 바뀌어,
멘트 하나를 추가할 때마다 페르소나 전체를 다시 들어봐야 한다.

실제로 tempo.close_eyes_again을 추가하고 재생성을 잊어 그 한 줄만 표준어로
나갔다. 증분이면 "빠진 줄 N개"가 눈에 보이므로 잊기 어렵다.

출력은 `agents/tools/persona_lines/<id>.json`.
검사(agents/tools/line_validator.py)에 걸린 줄은 저장하지 않는다 — 그 줄은
런타임에 중립 원문으로 발화된다. 말투가 안 바뀐 문장 하나가 게임이 멈추는
것보다 낫다.

실패 리포트가 곧 프롬프트 수정의 근거다. "슬롯 유실 5건"이면 슬롯 규칙을
강화하고, "영문 표기 유실 2건"이면 점수판 칸 이름 예시를 추가한다.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from agents.personas import PERSONAS, get_persona  # noqa: E402
from agents.tools import lines, llm  # noqa: E402
from agents.tools.line_validator import format_report, validate_all  # noqa: E402
from core.persona import Persona  # noqa: E402

# 한 번에 넘길 줄 수. 너무 크면 뒤쪽 문장의 말투가 흐려지고, 너무 작으면
# 호출 수만 늘어난다.
_BATCH = 20
_TIMEOUT = 60.0

_TASK_RULES = """\
아래 문장들을 당신의 말투로 다시 쓰세요.

이것은 번역이 아니라 캐릭터 연기다. 어미만 다듬고 끝내지 말 것.
당신의 말버릇, 호칭, 감탄사, 끊어 치는 리듬을 실제로 넣어야 한다.
바꾼 문장만 따로 읽었을 때 누가 말하는지 알 수 있어야 한다.

바꿔야 하는 것:
- 어미와 말투 (존댓말/반말, 사투리, 특유의 종결어미)
- 호칭과 부르는 말
- 문장 리듬 (짧게 끊거나, 늘어뜨리거나)
- 감탄사·말버릇·비속어

바꾸면 안 되는 것:
- {} 로 감싼 슬롯. 글자 그대로 남기고 값을 채워 넣지 않는다.
  ("{player}님 차례입니다" → "{player} 니 차례다"  O
   "{player}님 차례입니다" → "성민이 차례다"        X)
- 숫자. "카드 2장"은 그대로 2장이다.
- 영문 표기(4 of a Kind, L. Straight, Yacht 등). 화면 점수판에 적힌 이름이라
  번역하면 플레이어가 그 칸을 못 찾는다.
- 역할 이름(예언자, 도둑, 늑대인간 등)과 지시 내용.
- 빈 문자열은 빈 문자열 그대로.

길이는 원문과 비슷하게. 설명을 덧붙이지 말 것.

읽히는 문장이라는 것을 잊지 말 것:
- 이름 슬롯과 뒤따르는 말 사이에는 쉼표를 둔다. 쉼표가 없으면 TTS가 엉뚱한
  자리에서 끊는다("성민님풀 / 하우스 / 25점입니다").
- 붙여 쓴 이름(풀하우스, 스몰스트레이트 등)을 임의로 띄어 쓰지 않는다.
  띄우면 두 단어로 갈려 읽힌다.

입력은 {"line_id": "원문"} JSON이다. 같은 key로 {"line_id": "바꾼 문장"} JSON만
출력한다. 다른 말은 하지 않는다."""


def build_prompt(persona: Persona, batch: dict[str, str]) -> tuple[str, str]:
    """(system, user). 프롬프트를 눈으로 확인할 수 있게 함수로 뺀다.

    예시는 원문만 보여주면 안 된다. 그러면 모델이 "이런 게 들어오는구나"까지만
    알고 어미만 살짝 다듬고 만다. 원문→변환 쌍을 보여줘야 "이 정도까지
    바꾸라"가 전달된다.
    """
    system = f"{persona.style_prompt}\n\n{_TASK_RULES}"

    shots = {
        line_id: {"원문": lines.LINES[line_id], "변환": converted}
        for line_id, converted in persona.style_examples.items()
        if line_id in lines.LINES
    }
    parts = []
    if shots:
        parts.append(
            "다음은 당신의 말투로 바꾼 예시다. 이 정도로 확실히 바꿔야 한다:\n"
            + json.dumps(shots, ensure_ascii=False, indent=2)
        )
    parts.append("바꿀 문장:\n" + json.dumps(batch, ensure_ascii=False, indent=2))
    return system, "\n\n".join(parts)


async def _convert_batch(client, model: str, persona: Persona, batch: dict[str, str]) -> dict:
    system, user = build_prompt(persona, batch)
    resp = await asyncio.wait_for(
        client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        ),
        timeout=_TIMEOUT,
    )
    content = resp.choices[0].message.content
    if not content:
        return {}
    parsed = json.loads(content)
    return parsed if isinstance(parsed, dict) else {}


def _existing(persona_id: str) -> dict[str, str]:
    """이미 변환해 둔 줄. 없으면 빈 dict."""
    path = lines.PERSONA_LINES_DIR / f"{persona_id}.json"
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"  기존 파일을 읽지 못했습니다({exc}). 전부 새로 뽑습니다.")
        return {}
    return loaded if isinstance(loaded, dict) else {}


async def generate(persona_id: str, model: str, dry_run: bool, force: bool = False) -> int:
    persona = get_persona(persona_id)
    if persona.id != persona_id:
        print(f"'{persona_id}'는 없는 페르소나입니다. 가능: {', '.join(PERSONAS)}")
        return 1

    originals = dict(lines.LINES)
    kept = {} if force else _existing(persona_id)
    todo = {k: v for k, v in originals.items() if k not in kept}

    if not todo:
        print(f"  변환할 줄이 없습니다 (이미 {len(kept)}줄). 다시 뽑으려면 --force.")
        return 0
    if kept:
        print(f"  기존 {len(kept)}줄 유지, 빠진 {len(todo)}줄만 변환합니다.")

    items = list(todo.items())
    batches = [dict(items[i : i + _BATCH]) for i in range(0, len(items), _BATCH)]

    if dry_run:
        system, user = build_prompt(persona, batches[0])
        print("-- system " + "-" * 50)
        print(system)
        print(f"\n-- user (1/{len(batches)} 배치) " + "-" * 40)
        print(user[:1500] + ("\n... (생략)" if len(user) > 1500 else ""))
        return 0

    from openai import AsyncOpenAI

    if not os.environ.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY가 없습니다. .env를 확인하세요.")
        return 1
    client = AsyncOpenAI()

    converted: dict[str, str] = {}
    for index, batch in enumerate(batches, start=1):
        print(f"  배치 {index}/{len(batches)} ({len(batch)}줄) ...", flush=True)
        try:
            converted.update(await _convert_batch(client, model, persona, batch))
        except Exception as exc:  # noqa: BLE001 — 배치 하나가 죽어도 나머지는 살린다
            print(f"    실패: {type(exc).__name__}: {exc}")

    # 검사는 이번에 뽑은 줄만 대상으로 한다. 전체를 넘기면 손대지도 않은
    # 기존 줄이 "변환 누락"으로 잡혀 리포트가 쓸모없어진다.
    accepted, rejected = validate_all(todo, converted)
    print()
    print(format_report(todo, accepted, rejected))

    if not accepted:
        print("\n저장할 것이 없습니다.")
        return 1

    merged = {**kept, **accepted}
    lines.PERSONA_LINES_DIR.mkdir(parents=True, exist_ok=True)
    out = lines.PERSONA_LINES_DIR / f"{persona.id}.json"
    out.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"\n저장: {out} (새로 {len(accepted)}줄, 합계 {len(merged)}/{len(originals)}줄)")
    return 0


def main() -> int:
    # 윈도우 콘솔 기본 인코딩(cp949)으로는 한글 문장이 섞인 출력이 깨진다.
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser()
    parser.add_argument("persona", nargs="?", help="페르소나 id")
    parser.add_argument("--all", action="store_true", help="모든 페르소나 변환")
    parser.add_argument("--model", default=os.environ.get("LLM_MODEL", llm.DEFAULT_MODEL))
    parser.add_argument("--dry-run", action="store_true", help="프롬프트만 출력")
    parser.add_argument(
        "--force", action="store_true", help="이미 변환된 줄까지 전부 다시 뽑는다"
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")

    targets = list(PERSONAS) if args.all else ([args.persona] if args.persona else [])
    if not targets:
        parser.error("페르소나 id를 주거나 --all을 쓰세요.")

    code = 0
    for persona_id in targets:
        print(f"\n=== {persona_id} ===")
        code |= asyncio.run(generate(persona_id, args.model, args.dry_run, args.force))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
