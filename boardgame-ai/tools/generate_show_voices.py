"""발표 연출의 목소리를 파일로 뽑아 둔다.

관리자 콘솔의 버튼은 합성하지 않고 **미리 만들어 둔 파일을 그대로 튼다**
(backend/show_acts.py 머리말 참고). 그 파일을 만드는 것이 이 도구다.

사용:
    python3 tools/generate_show_voices.py            # 없는 것만 만든다
    python3 tools/generate_show_voices.py --force    # 전부 다시 만든다
    python3 tools/generate_show_voices.py --check    # 만들지 않고 상태만 본다

.env의 TYPECAST_API_KEY가 필요하다. 결과는 audio/assets/show/ 아래에 저장되고
**저장소에 함께 커밋한다** — 발표장에서 다시 만들 수 없기 때문이다.

## 문장이나 페르소나를 바꿨다면

반드시 다시 돌린다. 안 그러면 화면 자막과 실제 목소리가 다른 말을 한다. 파일
옆에 원문과 목소리 설정을 적은 .txt를 함께 남겨서, --check가 그 어긋남을
찾아낸다.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
from dataclasses import asdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(_PROJECT_ROOT / ".env")

from audio.catalog import SHOW_DIR  # noqa: E402
from audio.tts.base import get_provider  # noqa: E402
from backend.show_acts import ShowAct, build_show_acts  # noqa: E402


def _stamp_path(act: ShowAct) -> Path:
    """이 음원이 무엇으로 만들어졌는지 적어 두는 곳.

    파일만 보면 안에 무슨 말이 담겼는지 알 수 없다. 문장을 고쳤는데 음원을
    다시 안 만든 상태가 제일 위험한데(자막과 소리가 다른 말을 한다), 그걸
    눈으로 알아챌 방법이 없다. 옆에 원문을 적어 두면 --check가 잡아낸다.
    """
    return act.voice_path.with_suffix(".txt")


def _stamp(act: ShowAct) -> str:
    return json.dumps(
        {"text": act.text, "persona": act.persona_id, "voice": asdict(act.voice())},
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )


def _is_current(act: ShowAct) -> bool:
    """음원이 지금 정의와 맞는가."""
    if not act.voice_path.exists():
        return False
    stamp = _stamp_path(act)
    if not stamp.exists():
        # 옛 방식으로 만들어진 파일. 내용을 확인할 방법이 없으니 다시 만든다.
        return False
    return stamp.read_text(encoding="utf-8") == _stamp(act)


def main() -> int:
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description="발표 연출 음원 생성")
    parser.add_argument("--force", action="store_true", help="이미 있어도 다시 만든다")
    parser.add_argument("--check", action="store_true", help="만들지 않고 상태만 본다")
    args = parser.parse_args()

    acts = build_show_acts()
    SHOW_DIR.mkdir(parents=True, exist_ok=True)

    stale = [act for act in acts if not _is_current(act)]
    if args.check:
        for act in acts:
            mark = "OK " if act not in stale else "필요"
            print(f"[{mark}] {act.id:14s} {act.persona_name:8s} {act.text}")
        print(f"\n{len(acts)}개 중 {len(stale)}개를 다시 만들어야 합니다.")
        return 1 if stale else 0

    todo = list(acts) if args.force else stale
    if not todo:
        print(f"전부 최신입니다 ({len(acts)}개). 다시 만들려면 --force.")
        return 0

    provider = get_provider()
    if not provider.is_available():
        print(f"합성할 수 없습니다: {provider.unavailable_reason()}", file=sys.stderr)
        print(".env에 TYPECAST_API_KEY를 넣으세요.", file=sys.stderr)
        return 1

    failed = 0
    for act in todo:
        voice = act.voice()
        print(f"→ {act.id} ({act.persona_name}) {act.text}")
        try:
            data = provider.synthesize_sync(act.text, voice)
        except Exception as exc:  # noqa: BLE001 — 한 줄이 실패해도 나머지는 만든다
            print(f"   실패: {exc}", file=sys.stderr)
            failed += 1
            continue
        if not data:
            print("   실패: 빈 응답", file=sys.stderr)
            failed += 1
            continue
        act.voice_path.write_bytes(data)
        _stamp_path(act).write_text(_stamp(act), encoding="utf-8")
        print(f"   저장 {act.voice_path.relative_to(_PROJECT_ROOT)} ({len(data):,} bytes)")

    print(f"\n{len(todo) - failed}/{len(todo)}개 생성됨.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
