# 페르소나 말투 변환 결과

`<페르소나 id>.json` 하나가 그 페르소나의 말투다. `line_id → 변환된 문장`.

- 생성: `python tools/generate_persona_lines.py <id>` (LLM 필요)
- 적용: 서버 기동 시 자동. 없으면 중립 원문으로 진행한다.
- 검사: 로드 시점에 `agents/tools/line_validator.py`가 검사하고,
  걸린 줄은 빼버린다(그 줄만 원문으로 발화).

전부 채울 필요 없다. 몇 줄만 있어도 그 줄만 말투가 바뀐다.
