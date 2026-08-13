"""페르소나 목소리를 실제로 뽑아 들어본다.

서버를 띄우지 않고 wav 파일로 저장한다. 목소리·속도·감정 설정은 숫자만 봐서는
판단이 안 된다 — 0.90이 능청스러운지 답답한지는 들어봐야 안다.

사용:
    python tools/tts_preview.py                    # 전체 페르소나 × 대표 대사
    python tools/tts_preview.py angry              # 한 페르소나만
    python tools/tts_preview.py --text "야 밤이다"  # 임의 문장
    python tools/tts_preview.py --roles            # 말투(기본/심판/흥분)도 함께

결과는 out/tts_preview/<페르소나>/ 아래. 캐시를 거치지 않고 매번 새로 합성한다
(설정을 고쳐가며 듣는 것이 목적이라 캐시가 오히려 방해된다).
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

_OUT_DIR = _PROJECT_ROOT / "out" / "tts_preview"

from games.yacht.fsm import _CATEGORY_TTS_LABELS  # noqa: E402

_SCORE_LABEL = _CATEGORY_TTS_LABELS["full_house"]

# 성격이 다른 대사를 고른다. 한 문장만 들으면 그 문장에만 맞는 설정을 고르게 된다.
# line_id로 갖고 있어야 페르소나 말투가 적용된 문장으로 들을 수 있다.
_SAMPLES: dict[str, tuple[str, dict[str, object]]] = {
    "01_phase": ("werewolf.night_start", {}),
    "02_turn": ("yacht.turn_start", {"player": "성민"}),
    # 족보 이름은 실제 소스에서 가져온다. 여기 적어두면 소스가 바뀌어도
    # 프리뷰만 옛 표기로 남아, 정작 확인하려던 끊어읽기를 못 본다.
    "03_score": (
        "yacht.score_recorded",
        {"scorer": "성민", "label": _SCORE_LABEL, "score": 25, "next": "형승"},
    ),
    "04_warn": ("rules.wrong_turn", {"player": "성민"}),
    "05_hurry": ("tempo.hurry", {}),
}


def main() -> int:
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser()
    parser.add_argument("persona", nargs="?", default="", help="페르소나 id (기본: 전체)")
    parser.add_argument("--text", default="", help="이 문장만 합성")
    parser.add_argument(
        "--roles", action="store_true", help="기본/심판/흥분 말투를 각각 합성"
    )
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")

    from agents.personas import PERSONAS
    from agents.tools import lines
    from audio.tts.typecast import TypecastProvider
    from core.constants import AgentRole
    from core.persona import DELIVERY_EXCITED

    provider = TypecastProvider()
    if not provider.is_available():
        print(f"합성할 수 없습니다: {provider.unavailable_reason()}")
        return 1

    targets = (
        {args.persona: PERSONAS[args.persona]}
        if args.persona in PERSONAS
        else PERSONAS
    )
    if args.persona and args.persona not in PERSONAS:
        print(f"'{args.persona}'는 없는 페르소나입니다. 가능: {', '.join(PERSONAS)}")
        return 1

    # 말투별로 들을 때는 그 말투에 어울리는 대사를 붙여야 차이가 들린다.
    roles: list[tuple[str, str | None]] = [("base", None)]
    if args.roles:
        roles += [
            ("referee", AgentRole.REFEREE.value),
            ("excited", DELIVERY_EXCITED),
        ]

    total = ok = 0
    for persona in targets.values():
        out_dir = _OUT_DIR / persona.id
        out_dir.mkdir(parents=True, exist_ok=True)

        # 페르소나 말투를 적용해 실제로 나갈 문장으로 만든다. 중립 원문으로
        # 들으면 목소리만 확인되고 캐릭터는 확인되지 않는다.
        applied, _rejected = lines.use_persona(persona.id)
        samples = (
            {"custom": args.text}
            if args.text
            else {
                key: lines.render(line_id, **params) or ""
                for key, (line_id, params) in _SAMPLES.items()
            }
        )

        print(f"\n=== {persona.display_name} ({persona.id}) ===")
        print(f"    voice_id={persona.voice_name}  말투 {applied}줄 적용")

        for role_label, role in roles:
            voice = persona.voice_for(role)
            for key, text in samples.items():
                total += 1
                label = f"{key}_{role_label}" if args.roles else key
                path = out_dir / f"{label}.wav"
                try:
                    audio = provider.synthesize_sync(text, voice)
                except Exception as exc:  # noqa: BLE001 — 원인을 그대로 보여준다
                    print(f"  x {label:<20} {type(exc).__name__}: {exc}")
                    continue
                path.write_bytes(audio)
                ok += 1
                print(f"  o {label:<20} {text}")

    print(f"\n{ok}/{total} 성공 → {_OUT_DIR}")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
