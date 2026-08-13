"""쓸 수 있는 Typecast 보이스 목록.

페르소나에 넣을 voice_id를 여기서 찾는다. 콘솔에서 보이는 이름(칼란, 박창수,
발키리 등)만 알고 id는 모르는 상태에서 시작하기 때문이다.

사용:
    python tools/tts_voices.py            # 전체
    python tools/tts_voices.py 칼란       # 이름으로 검색
    python tools/tts_voices.py --raw      # 응답 원본(스키마 확인용)

필요한 것: .env에 TYPECAST_API_KEY
찾은 id는 agents/personas.py의 voice_name에 넣는다.

합성은 하지 않는다. 목록 조회만 한다.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))


def _field(voice: dict, *names: str) -> str:
    """응답 스키마가 조금 달라도 살아남게 후보 키를 훑는다."""
    for name in names:
        value = voice.get(name)
        if isinstance(value, str) and value:
            return value
    return ""


def main() -> int:
    # 윈도우 콘솔 기본 인코딩(cp949)으로는 한글이 섞인 출력이 깨진다.
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser()
    parser.add_argument("query", nargs="?", default="", help="이름 일부로 검색")
    parser.add_argument("--raw", action="store_true", help="응답 원본 JSON 출력")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")

    from agents.personas import PERSONAS
    from audio.tts.typecast import TypecastProvider

    provider = TypecastProvider()
    if not provider.is_available():
        print(f"보이스 목록을 못 가져왔습니다: {provider.unavailable_reason()}")
        print("  -> boardgame-ai/.env 에 TYPECAST_API_KEY=... 를 넣으세요.")
        return 1

    try:
        voices = provider.list_voices()
    except Exception as exc:  # noqa: BLE001 — 원인을 그대로 보여주는 게 목적
        print(f"보이스 목록 조회 실패: {type(exc).__name__}: {exc}")
        return 2

    if args.raw:
        print(json.dumps(voices, ensure_ascii=False, indent=2))
        return 0

    query = args.query.strip()
    rows = []
    for voice in voices:
        if not isinstance(voice, dict):
            continue
        name = _field(voice, "voice_name", "name", "display_name")
        voice_id = _field(voice, "voice_id", "id")
        models = voice.get("model") or voice.get("models") or ""
        if query and query not in name:
            continue
        rows.append((name, voice_id, str(models)))

    print(f"{len(rows)}개" + (f" (검색: {query})" if query else "") + "\n")
    for name, voice_id, models in sorted(rows):
        print(f"  {name:<20} {voice_id:<40} {models}")

    print("\n-- 페르소나에 설정된 보이스 " + "-" * 20)
    known = {voice_id for _, voice_id, _ in rows}
    for persona in PERSONAS.values():
        if not persona.voice_name:
            print(f"  {persona.id:<14} (미설정)  {persona.display_name}")
        else:
            mark = "" if persona.voice_name in known else "   ?? 목록에 없음"
            print(f"  {persona.id:<14} {persona.voice_name}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
