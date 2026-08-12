"""agents/lines.py — 멘트 단일 소유자 계약.

이 파일이 지키는 것:
1. line_id 조립 규칙(`<game_type>.<fsm_state>`)이 실제 FSM 상태명과 맞물린다.
2. 슬롯 치환이 발화를 죽이지 않는다 (KeyError로 TTS가 통째로 사라지는 사고 방지).
3. 멘트를 옮기면서 문장이 바뀌지 않았다 — ProgressAgent가 내는 결과가 이전과 동일.
4. STATIC_LINES와의 캐시 정합성 현황을 기록한다.
"""

from __future__ import annotations

import pytest

from agents import lines
from agents.context import AgentContext
from agents.progress_agent import ProgressAgent
from audio.catalog import STATIC_LINES
from core.audio import AudioPriority
from games.werewolf.ontology import NIGHT_PHASES, WerewolfPhase


def _ctx(game_type: str, fsm_state: str, active: str | None = None) -> AgentContext:
    return AgentContext(
        game_type=game_type,
        fsm_state=fsm_state,
        active_player=active,
        players=[{"player_id": "p1", "playername": "성민"}],
    )


# ── 1. line_id 규칙 ────────────────────────────────────────────────────────────


def test_모든_야간_페이즈에_멘트가_있다() -> None:
    """NIGHT_PHASES에 페이즈를 추가하고 멘트를 빠뜨리면 그 페이즈는 침묵한다."""
    for phase in (WerewolfPhase.NIGHT_START, *NIGHT_PHASES):
        for game_type in ("werewolf", "werewolf_practice"):
            line_id = f"{game_type}.{phase.value}"
            assert lines.get(line_id), f"{line_id} 멘트 없음"


def test_없는_line_id는_None() -> None:
    assert lines.get("werewolf.존재하지_않는_페이즈") is None
    assert lines.render("yacht.아직_안_옮긴_것", player="성민") is None


# ── 2. 슬롯 치환 ───────────────────────────────────────────────────────────────


def test_슬롯을_이름으로_채운다() -> None:
    assert lines.render("rules.wrong_turn", player="성민") == "지금은 성민님의 차례입니다."


def test_params가_없어도_죽지_않는다() -> None:
    """str.format이었다면 KeyError로 발화 자체가 사라진다."""
    assert lines.render("rules.wrong_turn") == "지금은 님의 차례입니다."


def test_모르는_슬롯은_무시한다() -> None:
    assert lines.fill("{a}와 {b}", a="가", b="나", c="다") == "가와 나"


# ── 3. 이관 회귀 방지 — 문장이 바뀌지 않았는가 ────────────────────────────────
# 이관 전 progress_agent.py의 _WEREWOLF_SCRIPTS/_WEREWOLF_PRACTICE_SCRIPTS에
# 있던 원문. 여기가 깨지면 TTS 캐시 키가 달라져 prewarm이 통째로 무효화된다.

_원문_샘플 = {
    "werewolf.night_start": "밤이 되었습니다. 모두 눈을 감아주세요.",
    "werewolf.night_seer": (
        "예언자는 깨어나세요. 다른 플레이어 1명 또는 중앙 카드 2장을 확인할 수 있습니다."
    ),
    "werewolf.night_insomniac": "불면증환자는 깨어나세요. 자신의 카드를 확인하세요.",
    "werewolf_practice.night_start": (
        "밤이 되었습니다. 튜토리얼 모드에서는 눈을 감지 않고 역할 순서대로 행동을 진행합니다."
    ),
    "rules.wrong_turn_unknown": "지금은 다른 플레이어의 차례입니다.",
    "rules.invalid_action": "지금은 해당 행동을 할 수 없습니다.",
    "tempo.half": "절반의 시간이 지났습니다.",
    "tempo.hurry": "시간이 얼마 남지 않았습니다.",
    "tempo.almost": "시간이 거의 다 됐습니다!",
}


@pytest.mark.parametrize(("line_id", "expected"), _원문_샘플.items())
def test_이관하면서_문장이_바뀌지_않았다(line_id: str, expected: str) -> None:
    assert lines.get(line_id) == expected


def test_progress_agent가_lines에서_읽는다() -> None:
    agent = ProgressAgent()
    result = agent.on_state_change(_ctx("werewolf", "night_seer"))
    assert result is not None
    assert result.tts_text == lines.get("werewolf.night_seer")
    assert result.priority == AudioPriority.NORMAL


def test_같은_페이즈는_한_번만_발화한다() -> None:
    agent = ProgressAgent()
    assert agent.on_state_change(_ctx("werewolf", "night_seer")) is not None
    assert agent.on_state_change(_ctx("werewolf", "night_seer")) is None


def test_요트는_last_message를_그대로_쓴다() -> None:
    """요트 멘트는 아직 FSM 소유 — 2단계에서 cue 채널로 옮긴다."""
    agent = ProgressAgent()
    ctx = _ctx("yacht", "AWAITING_ROLL")
    ctx.game_specific = {"last_message": "성민님, 주사위를 굴려주세요."}
    result = agent.on_state_change(ctx)
    assert result is not None
    assert result.tts_text == "성민님, 주사위를 굴려주세요."


# ── 4. TTS 캐시 정합성 현황 ────────────────────────────────────────────────────
# STATIC_LINES에 없는 멘트는 부팅 prewarm을 못 받아 첫 발화에 합성 지연이 붙는다.
# 아래는 이관 시점의 기존 갭을 그대로 기록한 것 — 이관이 만든 문제가 아니다.
# 갭을 메우거나 새 멘트를 추가하면 이 테스트가 알려준다.

_기존_캐시_갭 = {
    "werewolf.night_robber",
    "werewolf.night_troublemaker",
    *{f"werewolf_practice.{p.value}" for p in (WerewolfPhase.NIGHT_START, *NIGHT_PHASES)},
}


def test_캐시_갭_현황이_그대로다() -> None:
    실제_갭 = {
        line_id
        for line_id, text in lines.LINES.items()
        if line_id.startswith("werewolf") and text not in STATIC_LINES
    }
    assert 실제_갭 == _기존_캐시_갭, (
        "prewarm 대상이 달라졌다. 멘트를 고쳤다면 audio/catalog.py의 "
        "STATIC_LINES도 같이 고칠 것 (캐시 키가 텍스트 기반이라 한 글자만 달라도 miss)."
    )
