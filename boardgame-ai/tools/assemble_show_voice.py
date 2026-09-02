"""합성이 막혔을 때, 이미 캐시에 있는 문장을 이어붙여 발표용 음원을 만든다.

이건 **구조용 도구**다. 정상 경로는 tools/generate_show_voices.py 이고, 그쪽이
막혔을 때만 쓴다.

## 왜 필요한가

발표용 음원은 Typecast로 만든다. 그런데 무료 계정은 한도를 넘기면 계정 단위로
막히고(403 UNUSUAL_ACTIVITY_DETECTED), 그러면 **어떤 문장도, 어떤 목소리로도**
합성할 수 없다. 발표 전날 이걸 만나면 버튼 하나가 통째로 조용해진다.

그런데 서버는 부팅할 때마다 진행 멘트를 미리 합성해 둔다(audio/prewarm.py).
그 캐시에는 같은 페르소나, 같은 목소리로 만들어진 문장이 수백 개 쌓여 있다.
발표에서 하려는 말이 실제 게임의 멘트와 같다면 — 같아야 정직하기도 하다 —
새로 합성할 것 없이 그것들을 이어붙이면 된다.

## 쓰는 법

    python3 tools/assemble_show_voice.py strategy \\
        coach.reroll_mechanic coach.hand_small_straight_chase

문장 id는 agents/tools/persona_lines/<페르소나>.json 의 키다. 연출의 페르소나
목소리로 캐시를 뒤지므로, 페르소나가 다르면 찾지 못한다.

이어붙인 문장이 연출의 text와 다르면 거부한다. 자막과 목소리가 다른 말을 하는
것은 음원이 아예 없는 것보다 나쁘다.

## 만들어진 음원은 임시다

옆에 남기는 기록(.txt)에 source를 적어두므로, generate_show_voices.py 는 이걸
"아직 제대로 안 만든 것"으로 보고 --check 에서 계속 짚어준다. 합성이 풀리면
그쪽을 한 번 돌려 제대로 된 한 문장으로 갈아끼운다.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import wave
from array import array
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from dataclasses import asdict  # noqa: E402

from audio.catalog import (  # noqa: E402
    DYNAMIC_CACHE_DIR,
    SESSION_CACHE_DIR,
    STATIC_CACHE_DIR,
)
from audio.tts_engine import _make_cache_key  # noqa: E402
from backend.show_acts import ShowAct, build_show_acts  # noqa: E402

# 문장 사이에 넣는 쉼. 두 음원을 그냥 붙이면 앞 문장이 끝나기 무섭게 다음이
# 시작해 한 문장을 급하게 읽은 것처럼 들린다.
_PAUSE_MS = 320

# 이보다 작은 진폭은 무음으로 본다 (16비트 최대값의 1%).
_SILENCE_LEVEL = 328

# 문장 끝에 남겨두는 여운. 0으로 자르면 말끝이 뚝 끊긴다.
_KEEP_TAIL_MS = 90


def _cache_dirs() -> list[Path]:
    dirs = [STATIC_CACHE_DIR, DYNAMIC_CACHE_DIR]
    dirs += [p for p in SESSION_CACHE_DIR.glob("*") if p.is_dir()]
    return [d for d in dirs if d.exists()]


def _persona_lines(persona_id: str) -> dict[str, str]:
    path = _PROJECT_ROOT / "agents" / "tools" / "persona_lines" / f"{persona_id}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    lines = data.get("lines", data)
    return {k: v for k, v in lines.items() if isinstance(v, str)}


def _find_cached(text: str, act: ShowAct) -> Path | None:
    key = _make_cache_key(text, act.voice())
    for d in _cache_dirs():
        path = d / f"{key}.wav"
        if path.exists():
            return path
    return None


def _read(path: Path) -> tuple[tuple[int, int, int], array[int]]:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2:
            raise SystemExit(f"16비트가 아닌 음원은 다루지 않는다: {path}")
        params = (w.getnchannels(), w.getsampwidth(), w.getframerate())
        samples = array("h")
        samples.frombytes(w.readframes(w.getnframes()))
    return params, samples


def _trim(samples: array[int], rate: int, channels: int) -> array[int]:
    """앞뒤 무음을 걷어내고 짧은 여운만 남긴다.

    TTS 음원은 앞뒤에 무음이 붙어 나온다. 그대로 이으면 그 무음 두 개가 겹쳐
    문장 사이가 어색하게 길어진다. 여기서 걷어내고 쉼을 우리가 정한 길이로 준다.
    """
    loud = [i for i, v in enumerate(samples) if abs(v) > _SILENCE_LEVEL]
    if not loud:
        return samples
    keep = int(rate * channels * _KEEP_TAIL_MS / 1000)
    start = max(0, loud[0] - keep)
    end = min(len(samples), loud[-1] + keep)
    return samples[start:end]


def main() -> int:
    with contextlib.suppress(AttributeError, OSError):
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    parser = argparse.ArgumentParser(description="캐시에서 발표용 음원 조립")
    parser.add_argument("act_id", help="발표 연출 id (backend/show_acts.py)")
    parser.add_argument("line_ids", nargs="+", help="이어붙일 문장 id (말하는 순서대로)")
    args = parser.parse_args()

    acts = {a.id: a for a in build_show_acts()}
    act = acts.get(args.act_id)
    if act is None:
        print(f"모르는 연출: {args.act_id} (가능: {', '.join(acts)})", file=sys.stderr)
        return 1

    lines = _persona_lines(act.persona_id)
    if not lines:
        print(f"{act.persona_id} 변환 파일이 없습니다.", file=sys.stderr)
        return 1

    pieces: list[tuple[str, str, Path]] = []
    for line_id in args.line_ids:
        text = lines.get(line_id)
        if text is None:
            print(f"없는 문장 id: {line_id}", file=sys.stderr)
            return 1
        path = _find_cached(text, act)
        if path is None:
            print(f"캐시에 없음: {line_id} — 서버를 한 번 띄워 데워야 합니다.", file=sys.stderr)
            return 1
        pieces.append((line_id, text, path))

    joined = " ".join(text for _id, text, _p in pieces)
    if joined != act.text:
        print("이어붙인 문장이 연출의 자막과 다릅니다. 하나로 맞추세요.\n", file=sys.stderr)
        print(f"  조립: {joined}", file=sys.stderr)
        print(f"  자막: {act.text}", file=sys.stderr)
        return 1

    out = array("h")
    params: tuple[int, int, int] | None = None
    for line_id, _text, path in pieces:
        p, samples = _read(path)
        if params is None:
            params = p
        elif p != params:
            print(
                f"형식이 다른 음원은 이을 수 없습니다: {line_id} {p} != {params}",
                file=sys.stderr,
            )
            return 1
        if out:
            out.extend([0] * int(p[2] * p[0] * _PAUSE_MS / 1000))
        out.extend(_trim(samples, p[2], p[0]))
        print(f"  + {line_id:34s} {len(samples) / (p[2] * p[0]):.2f}초")

    assert params is not None
    channels, width, rate = params
    act.voice_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(act.voice_path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(width)
        w.setframerate(rate)
        w.writeframes(out.tobytes())

    # 옆에 남기는 기록. source가 들어가므로 generate_show_voices.py 는 이걸
    # "아직 제대로 안 만든 것"으로 보고 계속 짚어준다 — 합성이 풀리면
    # 한 문장짜리 제대로 된 음원으로 갈아끼우라는 뜻이다.
    stamp = {
        "text": act.text,
        "persona": act.persona_id,
        "voice": asdict(act.voice()),
        "source": "cache-assembled",
        "lines": [line_id for line_id, _t, _p in pieces],
    }
    act.voice_path.with_suffix(".txt").write_text(
        json.dumps(stamp, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )

    seconds = len(out) / (rate * channels)
    size = act.voice_path.stat().st_size
    print(f"\n{act.voice_path.relative_to(_PROJECT_ROOT)} — {seconds:.2f}초, {size:,} bytes")
    print("합성이 풀리면 tools/generate_show_voices.py 로 다시 만드세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
