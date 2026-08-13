"""페르소나 말투 변환 검증기.

LLM이 없어도 전부 검증된다 — 원문과 변환문 두 문자열을 비교하는 순수 함수라,
깨진 변환문을 손으로 써 넣어 잡히는지 확인하면 된다.

여기서 잡는 것들은 전부 실제로 게임을 멈추거나 거짓말을 하게 만드는 것들이다.
"""

from __future__ import annotations

import json

import pytest

from agents.tools import lines
from agents.tools.line_validator import format_report, validate_all, validate_line

# ── 슬롯 ───────────────────────────────────────────────────────────────────────


def test_슬롯이_유지되면_통과() -> None:
    assert validate_line("{scorer}님 {score}점입니다.", "야 {scorer} {score}점 먹었다.") == []


def test_슬롯이_값으로_박제되면_잡는다() -> None:
    """이게 통과하면 다음 사람 차례에도 '성민이 2점'이 나간다."""
    problems = validate_line("{scorer}님 {score}점입니다.", "야 성민이 2점 먹었다.")
    assert any("슬롯 유실" in p for p in problems)


def test_없던_슬롯을_만들어내면_잡는다() -> None:
    """채울 값이 없어 빈칸으로 렌더된다."""
    problems = validate_line("밤이 되었습니다.", "{player}야 밤이다.")
    assert any("없던 슬롯" in p for p in problems)


# ── 숫자 ───────────────────────────────────────────────────────────────────────


def test_숫자가_바뀌면_잡는다() -> None:
    """규칙 안내가 거짓말이 된다."""
    problems = validate_line("중앙 카드 2장을 확인할 수 있습니다.", "중앙 카드 3장 봐도 된다.")
    assert any("숫자" in p for p in problems)


def test_숫자가_빠지면_잡는다() -> None:
    problems = validate_line("카드 2장을 선택해주세요.", "카드 골라라.")
    assert any("숫자" in p for p in problems)


def test_숫자_순서가_달라도_통과() -> None:
    """말투를 바꾸면 어순이 바뀐다. 값만 같으면 된다."""
    assert validate_line("1명 또는 2장", "2장 아니면 1명") == []


# ── 점수판 칸 이름 ─────────────────────────────────────────────────────────────


def test_영문_칸_이름을_번역하면_잡는다() -> None:
    """화면 점수판에는 '4 of a Kind'라고 적혀 있어 한국어로 바꾸면 못 찾는다."""
    problems = validate_line("4 of a Kind 칸에 20점을 넣을 수 있어요.", "포카드 칸에 20점 넣어라.")
    assert any("영문 표기" in p for p in problems)


def test_영문_칸_이름을_그대로_두면_통과() -> None:
    assert (
        validate_line("4 of a Kind 칸에 20점을 넣을 수 있어요.", "야 4 of a Kind에 20점 박아라.")
        == []
    )


# ── TTS가 읽어버리는 것 ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "converted",
    [
        "**밤이다** 눈 감아라",
        "밤이다 🌙 눈 감아라",
        "밤이다. [중요] 눈 감아라",
        "# 밤이다",
    ],
)
def test_읽히면_안_되는_문자를_잡는다(converted: str) -> None:
    """'별표 별표 밤이다'로 읽힌다."""
    problems = validate_line("밤이 되었습니다.", converted)
    assert any("읽히면 안 되는" in p for p in problems)


def test_줄바꿈을_잡는다() -> None:
    problems = validate_line("밤이 되었습니다.", "밤이다.\n눈 감아라.")
    assert any("줄바꿈" in p for p in problems)


# ── 길이 ───────────────────────────────────────────────────────────────────────


def test_설명을_덧붙이면_잡는다() -> None:
    """낭독이 길어지면 진행이 늘어진다."""
    problems = validate_line(
        "밤이 되었습니다.",
        "자 이제 밤이 되었으니까 모두 눈을 감아야 하는데 왜냐하면 늑대인간이 "
        "행동할 시간이기 때문이고 훔쳐보면 게임이 재미없어지니까요.",
    )
    assert any("너무 길어짐" in p for p in problems)


def test_어미가_늘어나는_정도는_통과() -> None:
    assert validate_line("밤이 되었습니다.", "인자 밤 됐응게 눈 감어라잉?") == []


def test_빈_문장을_잡는다() -> None:
    assert validate_line("밤이 되었습니다.", "") != []
    assert validate_line("밤이 되었습니다.", "   ") != []


# ── 전체 검사 ──────────────────────────────────────────────────────────────────


def test_통과분과_실패분을_나눈다() -> None:
    originals = {"a": "{player}님 차례입니다.", "b": "밤이 되었습니다."}
    converted = {"a": "{player} 니 차례다.", "b": "밤이다 **집중**"}

    accepted, rejected = validate_all(originals, converted)

    assert accepted == {"a": "{player} 니 차례다."}
    assert "b" in rejected


def test_원문에_없는_line_id를_잡는다() -> None:
    """오타로 만든 항목이 조용히 섞이면 왜 안 바뀌는지 찾기 어렵다."""
    _, rejected = validate_all({"a": "밤."}, {"오타난키": "밤이다."})
    assert "오타난키" in rejected


def test_리포트가_사유별로_묶는다() -> None:
    originals = {"a": "{player}님 차례.", "b": "{player}님 차례.", "c": "카드 2장."}
    converted = {"a": "성민 차례.", "b": "형승 차례.", "c": "카드 3장."}
    accepted, rejected = validate_all(originals, converted)

    report = format_report(originals, accepted, rejected)
    assert "실패 3" in report
    assert "슬롯 유실 2건" in report


# ── 실제 멘트로 검사 ──────────────────────────────────────────────────────────


def test_원문끼리는_당연히_통과한다() -> None:
    """검사기가 지나치게 빡빡하면 정상 변환도 다 걸러낸다. 하한선 확인.

    실제로 이 테스트가 검사기 버그를 둘 잡았다 — 빈 원문(튜토리얼 부제)과
    원문에 이미 있던 대괄호(개발용 접두어)를 문제로 잡고 있었다.
    """
    accepted, rejected = validate_all(lines.LINES, dict(lines.LINES))
    assert rejected == {}
    assert len(accepted) == len(lines.LINES)


def test_원문이_빈_항목은_빈_변환이_정상() -> None:
    """튜토리얼은 '모두 눈을 뜨세요' 부제를 쓰지 않아 원문이 빈 줄이다."""
    assert validate_line("", "") == []
    assert validate_line("", "뭔가 생김") != []


def test_원문에_있던_기호는_문제_삼지_않는다() -> None:
    """개발용 '[개발]' 접두어처럼 의도적으로 넣은 것이 있다.
    LLM이 새로 붙인 것만 잡아야 한다."""
    assert validate_line("[개발] 후반 상황입니다.", "[개발] 후반 만들었다.") == []
    assert validate_line("[개발] 후반 상황입니다.", "[개발] **후반** 만들었다.") != []


# ── 페르소나 말투 적용 ────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_persona():
    yield
    lines.use_persona(None)


def test_변환_파일이_없으면_원문으로_진행한다() -> None:
    applied, rejected = lines.use_persona("존재하지_않는_페르소나")
    assert applied == 0 and rejected == {}
    assert lines.get("werewolf.night_start") == lines.original("werewolf.night_start")


def test_적용하면_get과_catalog가_바뀐다() -> None:
    lines.set_persona_lines("test", {"werewolf.night_start": "인자 밤 됐응게 눈 감어라잉?"})

    assert lines.get("werewolf.night_start") == "인자 밤 됐응게 눈 감어라잉?"
    assert lines.catalog()["werewolf.night_start"] == "인자 밤 됐응게 눈 감어라잉?"
    # 원문은 그대로 남아 있어야 다음 변환의 기준이 된다.
    assert lines.original("werewolf.night_start") == "밤이 되었습니다. 모두 눈을 감아주세요."


def test_변환하지_않은_줄은_원문으로_나간다() -> None:
    lines.set_persona_lines("test", {"werewolf.night_start": "밤이다."})
    assert lines.get("werewolf.morning") == lines.original("werewolf.morning")


def test_렌더도_페르소나_말투를_쓴다() -> None:
    lines.set_persona_lines("test", {"rules.wrong_turn": "야 지금 {player} 차례다."})
    assert lines.render("rules.wrong_turn", player="성민") == "야 지금 성민 차례다."


def test_파일에서_읽을_때도_검사한다(tmp_path, monkeypatch) -> None:
    """손으로 쓴 파일도 로드 시점에 걸린다 — 슬롯을 빠뜨리면 그 줄만 빠진다."""
    monkeypatch.setattr(lines, "PERSONA_LINES_DIR", tmp_path)
    (tmp_path / "testpersona.json").write_text(
        json.dumps(
            {
                "werewolf.night_start": "인자 밤 됐응게 눈 감어라잉?",
                "rules.wrong_turn": "야 지금 성민이 차례여.",  # 슬롯 유실
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    applied, rejected = lines.use_persona("testpersona")

    assert applied == 1
    assert "rules.wrong_turn" in rejected
    assert lines.get("werewolf.night_start") == "인자 밤 됐응게 눈 감어라잉?"
    # 걸린 줄은 원문으로 나간다. 게임은 계속된다.
    assert lines.get("rules.wrong_turn") == lines.original("rules.wrong_turn")


def test_깨진_json은_전체를_원문으로_돌린다(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(lines, "PERSONA_LINES_DIR", tmp_path)
    (tmp_path / "testpersona.json").write_text("{ 깨진", encoding="utf-8")

    applied, rejected = lines.use_persona("testpersona")

    assert applied == 0
    assert "__file__" in rejected


def test_말끝을_늘이는_물결표는_허용한다() -> None:
    """사투리·능청 말투에서 '햐유~'의 물결표를 막으면 캐릭터가 죽는다."""
    assert validate_line("천천히 하세요.", "천천히 햐유~") == []


def test_마크다운_취소선은_잡는다() -> None:
    """물결표 하나는 말끝, 둘은 마크다운이다."""
    assert validate_line("천천히 하세요.", "천천히 ~~햐유~~") != []
