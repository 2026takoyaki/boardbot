"""쓸 수 있는 한국어 TTS 보이스 목록.

페르소나를 먼저 정하고 목소리를 찾으면 순서가 뒤집힌다 — "장난기 있는 남성"을
정해놨는데 그런 목소리가 없으면 페르소나가 공중에 뜬다. 목록을 먼저 보고
목소리에 캐릭터를 붙이는 편이 빠르다.

사용:
    python tools/tts_voices.py            # 한국어 전체
    python tools/tts_voices.py --all      # 언어 무관 (Chirp 등 다국어 보이스 확인)

합성은 하지 않는다. 목록 조회만 하므로 과금 대상이 아니다.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections import defaultdict
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

# 이름에서 계열을 읽는다. 계열마다 자연스러움과 지원 파라미터가 다르다.
_FAMILY_ORDER = ("Chirp3-HD", "Chirp-HD", "Chirp", "Studio", "Neural2", "Wavenet", "Standard")


def _family(name: str) -> str:
    for family in _FAMILY_ORDER:
        if family.lower() in name.lower():
            return family
    return "기타"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--all", action="store_true", help="한국어 외 보이스도 표시")
    args = parser.parse_args()

    from dotenv import load_dotenv

    load_dotenv(_PROJECT_ROOT / ".env")
    creds = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")
    if not creds or not Path(creds).exists():
        print("GOOGLE_APPLICATION_CREDENTIALS가 없거나 파일이 없습니다. .env를 확인하세요.")
        return 1

    from google.api_core import exceptions as gexc
    from google.cloud import texttospeech

    client = texttospeech.TextToSpeechClient()
    try:
        response = client.list_voices(language_code=None if args.all else "ko-KR")
    except gexc.PermissionDenied as exc:
        # 목록 조회 자체는 무료지만 API 활성화 조건에 결제가 걸려 있다.
        # 스택트레이스를 그대로 뱉으면 원인이 안 보인다.
        print("보이스 목록을 못 가져왔습니다.\n")
        print(f"  {exc.message}\n")
        if "billing" in str(exc).lower():
            print("  → GCP 프로젝트 결제가 꺼져 있습니다. 켜면 그대로 다시 실행하면 됩니다.")
            print("     결제가 꺼져 있으면 TTS 합성도 전부 실패합니다.")
        return 2

    by_family: dict[str, list[tuple[str, str, int]]] = defaultdict(list)
    for voice in response.voices:
        if not args.all and not any(c.startswith("ko-") for c in voice.language_codes):
            continue
        by_family[_family(voice.name)].append(
            (voice.name, voice.ssml_gender.name, voice.natural_sample_rate_hertz)
        )

    total = sum(len(v) for v in by_family.values())
    print(f"총 {total}개\n")

    for family in (*_FAMILY_ORDER, "기타"):
        voices = sorted(by_family.get(family, []))
        if not voices:
            continue
        print(f"── {family} ({len(voices)}개) " + "─" * max(0, 40 - len(family)))
        for name, gender, rate in voices:
            print(f"  {name:<28} {gender:<8} {rate}Hz")
        print()

    # 페르소나가 지정한 보이스가 실제로 존재하는지, 성별이 의도와 맞는지 확인.
    # 지금 값은 결제가 막혀 목록을 못 본 상태에서 넣은 잠정치다.
    from agents.personas import PERSONAS

    print("── 페르소나가 쓰는 보이스 " + "─" * 22)
    known = {name: gender for names in by_family.values() for name, gender, _ in names}
    for persona in PERSONAS.values():
        gender = known.get(persona.voice_name, "?? 목록에 없음")
        print(f"  {persona.id:<10} {persona.voice_name:<28} {gender}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
