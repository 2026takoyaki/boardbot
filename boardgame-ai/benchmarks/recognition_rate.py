"""웨어울프 비전 인식 정확도 (지표 W).

웨어울프 비전이 담당하는 유일한 태스크 — 투표 지목 인식 — 의 정확도를
사용자의 수동 개입 신호로 측정한다.

역할 카드 인식은 인식률 문제로 제거됐다. 시스템이 플레이어의 역할을 알지 못하므로
역할 인식 정확도(role_recognition)라는 지표 자체가 더 이상 존재하지 않는다.

hook:
  vote_cast -       — 비전이 인식한 투표 (분모)
  vote_correction - — 사용자가 투표 오인식을 수동 정정 (인식 실패 proxy)

비전 인식 투표 수 대비 수동 정정 비율 → 정확도 추정 (상한 해석).
"""

from __future__ import annotations

import json
from pathlib import Path

from benchmarks.trace_collector import collect_to_list


def analyze(log_path: Path) -> dict:
    events = collect_to_list(log_path)

    casts = sum(1 for e in events if e["event"] == "vote_cast")
    corrections = sum(1 for e in events if e["event"] == "vote_correction")
    vote = {
        "vision_casts": casts,
        "manual_corrections": corrections,
        "correction_rate": round(corrections / casts, 4) if casts else 0.0,
        "estimated_accuracy": round(1 - corrections / casts, 4) if casts else None,
        "note": (
            "수동 정정 = 투표 오인식 proxy. 비전 인식 투표 수 대비 정정 비율. "
            "전략적 변심으로 누른 경우 포함되므로 상한값으로 해석."
        ),
    }

    return {"vote": vote}


def run(session_dir: Path) -> dict:
    log_path = session_dir / "raw" / "app.log"
    if not log_path.exists():
        return {"error": "no log"}
    result = analyze(log_path)
    (session_dir / "recognition_rate.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    return result
