"""agents/tools/lines.py — 멘트 단일 소유자 계약.

이 파일이 지키는 것:
1. line_id 조립 규칙(`<game_type>.<fsm_state>`)이 실제 FSM 상태명과 맞물린다.
2. 슬롯 치환이 발화를 죽이지 않는다 (KeyError로 TTS가 통째로 사라지는 사고 방지).
3. 멘트를 옮기면서 문장이 바뀌지 않았다 — ProgressAgent가 내는 결과가 이전과 동일.
4. 미리 만들어 둘 수 있는 멘트가 조용히 줄어들지 않는다.
"""

from __future__ import annotations

import asyncio

import pytest

from agents.context import AgentContext
from agents.progress_agent import ProgressAgent
from agents.tools import lines
from core.audio import AudioPriority
from core.events import GameEvent
from games.werewolf.ontology import NIGHT_PHASES, WerewolfPhase
from games.yacht import YachtEventType, YachtFSM, YachtInputType


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


def test_요트는_narration을_렌더해서_발화한다() -> None:
    agent = ProgressAgent()
    ctx = _ctx("yacht", "AWAITING_ROLL")
    ctx.game_specific = {
        "narration": {"line_id": "yacht.turn_start", "params": {"player": "성민"}},
    }
    result = agent.on_state_change(ctx)
    assert result is not None
    assert result.tts_text == "성민님, 주사위를 굴려주세요."


def test_narration이_last_message보다_우선한다() -> None:
    """둘 다 오면 구조화된 쪽을 쓴다 — 페르소나가 걸리는 건 narration 경로뿐."""
    agent = ProgressAgent()
    ctx = _ctx("yacht", "AWAITING_ROLL")
    ctx.game_specific = {
        "narration": {"line_id": "yacht.turn_start", "params": {"player": "성민"}},
        "last_message": "옛 경로 문장",
    }
    result = agent.on_state_change(ctx)
    assert result is not None
    assert result.tts_text == "성민님, 주사위를 굴려주세요."


def test_narration이_없으면_last_message로_폴백한다() -> None:
    """아직 안 옮긴 경로가 침묵하지 않도록. 전부 옮기면 이 폴백은 제거한다."""
    agent = ProgressAgent()
    ctx = _ctx("yacht", "AWAITING_ROLL")
    ctx.game_specific = {"last_message": "아직 안 옮긴 문장입니다."}
    result = agent.on_state_change(ctx)
    assert result is not None
    assert result.tts_text == "아직 안 옮긴 문장입니다."


# ── 3-2. 요트: FSM이 내보낸 line_id가 실제로 렌더되는가 ───────────────────────
# line_id는 문자열이라 오타가 나도 FSM은 조용히 통과한다. 그 페이즈만 침묵하고
# 원인은 로그에도 안 남는다. 실제 진행 경로를 돌려 전부 렌더되는지 확인한다.


def _yacht_roll(fsm: YachtFSM, dice: list[int], actor: str = "p1") -> None:
    fsm.handle_event(
        GameEvent(
            event_type=YachtEventType.ROLL_CONFIRMED.value,
            actor_id=actor,
            confidence=1.0,
            frame_id=0,
            data={"dice_values": dice, "keep_mask": [False] * 5},
        )
    )


def test_요트_진행_경로의_narration이_전부_렌더된다() -> None:
    fsm = YachtFSM(["p1", "p2"])
    seen: list[dict] = []

    def record() -> None:
        if fsm.state.narration:
            seen.append(dict(fsm.state.narration))

    fsm.start()
    record()
    _yacht_roll(fsm, [1, 1, 3, 4, 6])
    record()
    fsm.handle_input(
        YachtInputType.DICE_REROLL_REQUESTED.value,
        {"keep_mask": [True, True, False, False, False]},
    )
    record()
    _yacht_roll(fsm, [1, 1, 2, 5, 5])
    _yacht_roll(fsm, [1, 1, 2, 5, 6])  # 3굴림 완료
    record()
    fsm.handle_event(
        GameEvent(
            event_type=YachtEventType.DICE_ESCAPED.value,
            actor_id="p1", confidence=1.0, frame_id=0, data={},
        )
    )
    record()
    fsm.handle_input(
        YachtInputType.SCORE_CATEGORY_SELECTED.value, {"category": "ones"}, player_id="p1"
    )
    record()

    # 개수만 세면 안 된다 — 입력이 먹히지 않으면 FSM이 조용히 아무것도 하지 않고
    # 직전 narration이 그대로 남아 개수는 채워진다. 어떤 line_id가 나왔는지를
    # 봐야 경로를 실제로 통과했는지 알 수 있다.
    assert [n["line_id"] for n in seen] == [
        "yacht.turn_start",
        "yacht.roll_partial",
        "yacht.reroll_prompt",
        "yacht.roll_final",
        "yacht.dice_escaped",
        "yacht.score_recorded",
    ]
    for narration in seen:
        line_id = narration["line_id"]
        assert lines.get(line_id), f"{line_id}: LINES에 없는 line_id"
        rendered = lines.render(line_id, **narration["params"])
        assert rendered and "{" not in rendered, f"{line_id}: 렌더 실패 → {rendered!r}"


def test_요트_차례_위반은_wrong_turn을_낸다() -> None:
    fsm = YachtFSM(["p1", "p2"])
    fsm.start()
    _yacht_roll(fsm, [1, 2, 3, 4, 5], actor="p2")  # p1 차례인데 p2가 굴림
    assert fsm.state.narration == {
        "line_id": "yacht.wrong_turn",
        "params": {"player": "p1"},
    }


def test_narrate는_None_파라미터를_버린다() -> None:
    """슬롯이 빈 채로 렌더되는 편이 'None님 차례입니다'보다 낫다."""
    fsm = YachtFSM(["p1"])
    fsm.state.narrate("yacht.turn_start", player=None)
    assert fsm.state.narration == {"line_id": "yacht.turn_start", "params": {}}


# ── 4. TTS 캐시 정합성 ─────────────────────────────────────────────────────────
# 계층 판정은 tests/test_cache_layers.py가 본다. 여기서는 "미리 만들어 둘 수
# 있는 멘트가 조용히 줄어들지 않는가"만 확인한다 — 멘트에 슬롯을 하나 더
# 넣으면 그 줄은 부팅 prewarm 대상에서 빠져 첫 발화에 지연이 붙는다.


def test_대부분의_멘트는_미리_만들_수_있다() -> None:
    static_ratio = len(lines.static_texts()) / len(lines.LINES)
    assert static_ratio > 0.6, (
        f"미리 만들어 둘 수 있는 멘트가 {static_ratio:.0%}로 줄었다. "
        "슬롯을 늘리면 그만큼 런타임 합성이 늘어난다."
    )


# ── 5. 프론트 이관 계약 (NARRATION_REQUEST + 카탈로그) ────────────────────────
# 프론트는 문장이 아니라 line_id를 보내고, 화면에 그릴 문장은 접속 시 받은
# 카탈로그에서 읽는다. 둘 중 하나만 깨져도 화면이 비거나 음성이 사라진다.


class _FakeWS:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


class _FakeAudio:
    """세션이 붙잡는 AudioManager 표면만 흉내낸다. 발화 텍스트만 관찰하면 된다."""

    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def enqueue_tts(self, text: str, **kwargs: object) -> str:
        self.spoken.append(text)
        return "pb"

    def get_session_id(self) -> str | None:
        return None

    def attach_broadcast(self, *args: object, **kwargs: object) -> None:
        pass

    def detach_broadcast_if(self, *args: object, **kwargs: object) -> None:
        pass


def _werewolf_session(audio: _FakeAudio | None = None):
    from backend.werewolf_session import WerewolfSession

    return WerewolfSession(
        websocket=_FakeWS(),
        send_fusion_context_fn=lambda ctx, sv: None,
        loop=asyncio.get_event_loop(),
        audio_manager=audio,
    )


def test_카탈로그에_프론트가_쓰는_line_id가_전부_있다() -> None:
    """프론트 컴포넌트가 참조하는 id. 빠지면 그 화면이 빈칸으로 뜬다."""
    필요 = [
        "werewolf.setup_intro", "werewolf.setup_flip", "werewolf.setup_take",
        "werewolf.setup_place", "werewolf.setup_center", "werewolf.setup_close_eyes",
        "werewolf.setup_confirm", "werewolf.role_select_prompt",
        "werewolf.morning", "werewolf.discussion_start",
        "werewolf.vote_intro", "werewolf.game_end",
        "werewolf_practice.setup_no_hide", "werewolf_practice.morning",
        "werewolf_practice.day_rules",
        # 튜토리얼도 확인/투표 문구는 일반 모드를 물려받아야 한다.
        "werewolf_practice.setup_confirm", "werewolf_practice.vote_intro",
        *[f"werewolf.vote_count_{n}" for n in range(6)],
    ]
    catalog = lines.catalog()
    빠진_것 = [line_id for line_id in 필요 if not catalog.get(line_id)]
    assert 빠진_것 == []


def test_튜토리얼은_일반모드를_물려받되_다른_것만_덮어쓴다() -> None:
    assert lines.get("werewolf_practice.setup_confirm") == lines.get("werewolf.setup_confirm")
    assert lines.get("werewolf_practice.setup_take") != lines.get("werewolf.setup_take")


@pytest.mark.anyio
async def test_hello가_카탈로그를_실어_보낸다() -> None:
    session = _werewolf_session()
    await session.send_hello()
    hello = [m for m in session.websocket.sent if m["msg_type"] == "hello"][-1]
    assert hello["payload"]["lines"]["werewolf.morning"] == lines.get("werewolf.morning")


@pytest.mark.anyio
async def test_NARRATION_REQUEST가_line_id를_문장으로_바꿔_발화한다() -> None:
    audio = _FakeAudio()
    session = _werewolf_session(audio)
    await session.handle_client_message(
        {
            "input_type": "NARRATION_REQUEST",
            "data": {"line_id": "werewolf.role_select_prompt", "params": {"count": "다섯"}},
        }
    )
    assert audio.spoken == [
        "이번 게임에 사용할 카드 다섯장을 선택해주세요. "
        "선택한 카드만 테이블에 올려두고 나머지 카드는 정리해주세요."
    ]


@pytest.mark.anyio
async def test_없는_line_id는_조용히_무시한다() -> None:
    """오타 하나로 세션이 죽으면 안 된다. 그 멘트만 빠지고 게임은 계속된다."""
    audio = _FakeAudio()
    session = _werewolf_session(audio)
    await session.handle_client_message(
        {"input_type": "NARRATION_REQUEST", "data": {"line_id": "werewolf.없는거"}}
    )
    assert audio.spoken == []


def test_요트_인트로_line_id가_전부_있다() -> None:
    """YachtTutorial.jsx의 STEPS가 참조하는 id. 빠지면 그 카드가 무음이 된다."""
    catalog = lines.catalog()
    빠진_것 = [
        line_id
        for line_id in (
            "yacht.intro_what", "yacht.intro_turn",
            "yacht.intro_table", "yacht.intro_score",
        )
        if not catalog.get(line_id)
    ]
    assert 빠진_것 == []


def test_아침_안내가_제목과_부제로_나뉜다() -> None:
    """화면이 큰 제목 + 작은 부제로 보여주므로 문자열도 그 단위로 쪼개져 있어야
    프론트가 사본을 따로 들지 않는다."""
    assert lines.get("werewolf.morning") == "아침이 밝았습니다."
    assert lines.get("werewolf.morning_open_eyes") == "모두 눈을 뜨세요."
    # 튜토리얼은 눈을 감지 않았으므로 부제가 없다.
    assert lines.get("werewolf_practice.morning_open_eyes") == ""


@pytest.mark.anyio
async def test_요트_NARRATION_REQUEST가_문장으로_바꿔_발화한다() -> None:
    from backend.yacht_session import YachtSession

    ws = _FakeWS()
    session = YachtSession(ws)
    audio = _FakeAudio()
    session._audio_manager = audio  # type: ignore[assignment]

    await session.handle_client_message(
        {"input_type": "NARRATION_REQUEST", "data": {"line_id": "yacht.intro_turn"}}
    )
    assert audio.spoken == [lines.get("yacht.intro_turn")]


@pytest.mark.anyio
async def test_요트_같은_안내를_연달아_보내면_한_번만_읽는다() -> None:
    """튜토리얼 화면이 리렌더될 때마다 같은 요청을 보내는 경로가 있다."""
    from backend.yacht_session import YachtSession

    session = YachtSession(_FakeWS())
    audio = _FakeAudio()
    session._audio_manager = audio  # type: ignore[assignment]

    for _ in range(3):
        await session.handle_client_message(
            {"input_type": "NARRATION_REQUEST", "data": {"line_id": "yacht.intro_what"}}
        )
    assert len(audio.spoken) == 1
