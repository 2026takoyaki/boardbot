"""컨트롤 세션 — 조명·소리를 직접 다루는 자리.

게임이 아니라서 FSM도 비전도 없다. 여기서 지키는 것은 넷이다.

  - 사용자가 고른 밝기가 **그대로** 나간다 (다른 컨텍스트의 하한에 걸리지 않는다)
  - 연출이 끝나면 **사용자가 맞춰 둔 색**으로 돌아온다 (중립이 아니라)
  - 이상한 입력이 들어와도 죽지 않는다
  - 발표 연출은 **합성 없이** 나간다 (아래 발표 연출 절 참고)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from audio.manager import AudioManager
from backend.control_session import ControlSession
from backend.show_acts import build_show_acts
from bulb.config import LightConfig
from bulb.controller import LightController
from bulb.driver.mock import MockDriver
from bulb.scenes import CONTROL_CUES, NEUTRAL_SCENE
from core.envelope import WSMessage
from core.persona import VoiceConfig


class _FakeSocket:
    """보낸 것을 모아두는 가짜 소켓."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


class _ExplodingEngine:
    """합성을 시도하면 터지는 엔진.

    "실패해도 잘 돌아간다"가 아니라 **시도 자체가 없다**를 검사하려는 것이다.
    발표용 음원은 파일이 이미 있는데도 합성 경로를 타면, 캐시 키가 어긋나는
    순간(페르소나를 한 글자만 고쳐도 그렇다) 버튼이 조용해진다.
    """

    def cache_hit(self, *args: Any, **kwargs: Any) -> Path | None:
        raise AssertionError("발표 연출인데 캐시를 뒤졌다")

    async def synthesize(self, *args: Any, **kwargs: Any) -> Path | None:
        raise AssertionError("발표 연출인데 합성을 시도했다")

    def is_available(self, voice: VoiceConfig | None = None) -> bool:
        return False


def _session(driver: MockDriver) -> tuple[ControlSession, _FakeSocket]:
    sock = _FakeSocket()
    light = LightController(driver, LightConfig(command_timeout_s=0.5))
    # audio_manager는 넘기지 않는다. 소리는 이 테스트의 관심사가 아니고,
    # 없어도 조명 경로가 그대로 돌아야 한다(둘이 얽히면 안 된다).
    return ControlSession(sock, audio_manager=None, light_controller=light), sock  # type: ignore[arg-type]


async def _settle() -> None:
    for _ in range(20):
        await asyncio.sleep(0)


# ── 조명 직접 조절 ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_고른_밝기가_그대로_나간다() -> None:
    """다른 컨텍스트의 하한(요트 60%)에 걸리면 안 된다.

    game=None으로 넘기면 "모르는 컨텍스트"라 하한 60%가 걸려, 어둡게 내려도
    방이 안 어두워진다. 사용자가 고른 값과 실제 방이 어긋나는 것이 제일 나쁘다.
    """
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message(
        {"input_type": "CONTROL_SET_LIGHT", "data": {"color": [150, 60, 220], "brightness": 20}}
    )
    await _settle()

    color, brightness, *_ = driver.last
    assert color == (150, 60, 220)
    assert brightness == 20, "사용자가 고른 밝기가 하한에 걸려 올라갔다"


@pytest.mark.asyncio
async def test_요트_밝기_하한은_그대로_지켜진다() -> None:
    """컨트롤 하한을 0으로 연 것이 요트 인식 보호까지 풀면 안 된다."""
    driver = MockDriver()
    light = LightController(driver, LightConfig(command_timeout_s=0.5))

    await light.apply_manual((10, 10, 10), 5, game="yacht")
    await _settle()

    assert driver.last[1] == 60, "요트는 인식 때문에 어두워질 수 없다"


@pytest.mark.asyncio
async def test_이상한_입력에_죽지_않는다() -> None:
    driver = MockDriver()
    session, _ = _session(driver)

    bad = [
        {"color": "빨강", "brightness": 50},  # 색이 배열이 아님
        {"color": [1, 2], "brightness": 50},  # 길이가 모자람
        {"color": [-5, 300, "x"], "brightness": 999},  # 범위 밖 + 숫자가 아님
        {},  # 통째로 없음
    ]
    for payload in bad:
        await session.handle_client_message({"input_type": "CONTROL_SET_LIGHT", "data": payload})
    await _settle()

    # 마지막으로 통과한 값만 반영되고, 채널은 0~255 / 밝기는 5~100 안에 있어야 한다.
    if driver.last is not None:
        color, brightness, *_ = driver.last
        assert all(0 <= ch <= 255 for ch in color)
        assert 5 <= brightness <= 100


@pytest.mark.asyncio
async def test_밝기를_0까지_내릴_수_있다() -> None:
    """소등도 연출의 하나다. 하한을 두면 방을 완전히 끌 방법이 없어진다."""
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message(
        {"input_type": "CONTROL_SET_LIGHT", "data": {"color": [255, 255, 255], "brightness": 0}}
    )
    await _settle()

    assert driver.last[1] == 0


@pytest.mark.asyncio
async def test_전환_시간이_전구까지_그대로_간다() -> None:
    """ "즉시"와 "3초에 걸쳐"는 연출로서 다른 물건이다. 화면이 고른 값이
    중간에 다른 값으로 바뀌면 고르는 일 자체가 무의미해진다."""
    for fade in (0, 500, 3000):
        driver = MockDriver()
        session, sock = _session(driver)

        await session.handle_client_message(
            {
                "input_type": "CONTROL_SET_LIGHT",
                "data": {"color": [255, 200, 90], "brightness": 70, "duration_ms": fade},
            }
        )
        await _settle()

        assert driver.last[2] == fade, f"{fade}ms를 요청했는데 {driver.last[2]}ms로 나갔다"
        # 화면 색 띠도 같은 시간에 걸쳐 바뀌어야 방과 어긋나지 않는다.
        light_state = [m for m in sock.sent if m["msg_type"] == "light_state"][-1]
        assert light_state["payload"]["duration_ms"] == fade


@pytest.mark.asyncio
async def test_말도_안_되게_긴_전환은_잘린다() -> None:
    """슬라이더를 놓고 한참 뒤에 색이 도착하면 조작이 안 먹는 것으로 보인다."""
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message(
        {
            "input_type": "CONTROL_SET_LIGHT",
            "data": {"color": [255, 255, 255], "brightness": 50, "duration_ms": 999999},
        }
    )
    await _settle()

    from backend.control_session import _MAX_FADE_MS

    assert driver.last[2] == _MAX_FADE_MS


# ── 연출 버튼 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_연출이_끝나면_맞춰둔_색으로_돌아온다() -> None:
    """중립이 아니라 **사용자가 맞춰 둔 색**이어야 한다.

    중립으로 돌아가면 연출을 한 번 터뜨릴 때마다 방 색이 초기화돼,
    색을 맞춰 두는 일 자체가 무의미해진다.
    """
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message(
        {"input_type": "CONTROL_SET_LIGHT", "data": {"color": [150, 60, 220], "brightness": 40}}
    )
    await _settle()

    await session.handle_client_message({"input_type": "CONTROL_CUE", "data": {"cue": "applause"}})
    await asyncio.sleep(CONTROL_CUES["applause"].total_ms / 1000 + 0.4)

    color, brightness, *_ = driver.last
    assert color == (150, 60, 220)
    assert brightness == 40


@pytest.mark.asyncio
async def test_파티는_색이_여러_번_바뀌고_제일_길다() -> None:
    """파티만 색을 여러 번 밟는다. 나머지는 짧게 터지고 만다."""
    party = CONTROL_CUES["party"]
    others = [c for name, c in CONTROL_CUES.items() if name != "party"]

    assert len(party.steps) > 5, "파티인데 색이 몇 번 안 바뀐다"
    assert all(party.total_ms > c.total_ms * 2 for c in others), "파티가 충분히 길지 않다"

    driver = MockDriver()
    session, _ = _session(driver)
    await session.handle_client_message({"input_type": "CONTROL_CUE", "data": {"cue": "party"}})
    await asyncio.sleep(party.total_ms / 1000 + 0.5)

    colors = {color for color, _b, _d in driver.applied}
    assert len(colors) >= 5, f"파티인데 색이 {len(colors)}종뿐이다"


@pytest.mark.asyncio
async def test_없는_연출_이름은_무시된다() -> None:
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message({"input_type": "CONTROL_CUE", "data": {"cue": "없는것"}})
    await session.handle_client_message({"input_type": "CONTROL_CUE", "data": {}})
    await _settle()

    assert not driver.applied, "없는 연출인데 조명이 움직였다"


# ── 접속·종료 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_접속하면_연출_목록을_알려준다() -> None:
    """목록의 주인은 백엔드다. 화면이 자기 목록을 갖고 있으면 연출을 추가할 때
    한쪽만 고쳐서 눌러도 아무 일이 없는 버튼이 생긴다."""
    driver = MockDriver()
    session, sock = _session(driver)

    await session.send_hello()

    hello = sock.sent[0]
    assert hello["msg_type"] == "hello"
    payload = hello["payload"]
    assert payload["game_type"] == "control"
    assert {c["id"] for c in payload["cues"]} == set(CONTROL_CUES)
    for cue in payload["cues"]:
        assert cue["label"] and cue["duration_ms"] > 0


@pytest.mark.asyncio
async def test_나가면_조명이_원래대로_돌아온다() -> None:
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message(
        {"input_type": "CONTROL_SET_LIGHT", "data": {"color": [255, 0, 0], "brightness": 15}}
    )
    await _settle()
    assert driver.last[0] == (255, 0, 0)

    await session.restore_light()
    await _settle()

    assert driver.last[0] == NEUTRAL_SCENE.color
    assert driver.last[1] == NEUTRAL_SCENE.brightness


# ── 발표 연출 ─────────────────────────────────────────────────────────────────
#
# 발표장에서 실패할 수 있는 것을 전부 뺀 자리다. 여기서 지키는 것은 셋이다.
#
#   - 목소리는 **합성하지 않는다**. 미리 만들어 둔 파일이 그대로 나간다
#   - 조명은 실제 게임과 **같은 정의**를 쓴다 (비슷하게 다시 만든 것이 아니라)
#   - 화면 자막과 실제 음원이 같은 말을 한다


@pytest.mark.asyncio
async def test_발표_연출은_합성하지_않고_파일을_튼다() -> None:
    """발표장에서 인터넷이나 API 키에 기대면 안 된다.

    합성 경로를 타면 캐시 미스 한 번에 버튼이 조용해진다. 페르소나 정의를 한
    글자만 고쳐도 캐시 키가 바뀌어 전부 미스가 되므로, 그 한 번은 반드시 온다.
    """
    driver = MockDriver()
    session, sock = _session(driver)
    # 합성이 일어나면 즉시 터지는 엔진. 실패가 아니라 **시도 자체**를 잡는다.
    engine = _ExplodingEngine()
    audio = AudioManager(engine)  # type: ignore[arg-type]
    sent: list[WSMessage] = []

    async def collect(msg: WSMessage) -> None:
        sent.append(msg)

    audio.attach_broadcast(collect)
    session._audio = audio

    # 소리가 곧바로 나가는 연출로 본다(암전을 두는 것은 아래에서 따로 본다).
    act = next(a for a in build_show_acts(15) if a.id == "yacht_score")
    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {"act": act.id}})
    await _settle()
    # 큐는 ack 기반이라 효과음이 끝나야 목소리가 나간다. 실제 프론트가 하는 일.
    await audio.handle_ack(sent[0].payload["playback_id"], "played")
    await _settle()

    tts = [m for m in sent if m.msg_type == "tts_play"]
    assert tts, "발표 연출인데 목소리가 안 나갔다"
    assert tts[0].payload["audio_url"] == act.voice_url
    assert tts[0].payload["text"] == act.text, "자막과 음원이 다른 말을 한다"


@pytest.mark.asyncio
async def test_효과음이_목소리보다_먼저_나간다() -> None:
    """프론트는 한 번에 하나만 재생한다. 순서가 뒤집히면 늑대 울음이 멘트를
    자르고 들어온 것처럼 들린다."""
    driver = MockDriver()
    session, _ = _session(driver)
    audio = AudioManager(_ExplodingEngine())  # type: ignore[arg-type]
    sent: list[WSMessage] = []

    async def collect(msg: WSMessage) -> None:
        sent.append(msg)

    audio.attach_broadcast(collect)
    session._audio = audio

    act = next(a for a in build_show_acts(15) if a.id == "ww_werewolf")
    assert act.sfx and act.audio_delay_ms > 0
    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {"act": act.id}})

    # 암전이 끝나기 전에는 아무 소리도 나가면 안 된다. 캄캄해지기도 전에
    # 늑대가 울면 어둠이 연출로 안 읽힌다.
    await asyncio.sleep(act.audio_delay_ms / 1000 * 0.5)
    assert not sent, "암전이 끝나기 전에 소리가 나갔다"

    await asyncio.sleep(act.audio_delay_ms / 1000 * 0.6 + 0.2)
    # ack 기반이라 첫 항목만 나가 있다. 그 첫 항목이 효과음이어야 한다.
    assert sent[0].msg_type == "sfx_play"
    assert sent[0].payload["name"] == act.sfx


@pytest.mark.asyncio
async def test_밤_재현은_암전을_거쳐_들어간다() -> None:
    """늑대인간 밤은 "눈을 감으세요 / 뜨세요"가 한 쌍이다. 밝은 방에서 곧바로
    붉은색으로 갈아끼우면 조명이 뒤쪽만 말한다. 한 번 재웠다 올려야 한다.

    소리도 그 암전이 끝나는 지점에 들어온다 — 캄캄해지기도 전에 늑대가 울면
    어둠이 연출로 안 읽힌다.
    """
    driver = MockDriver()
    session, _ = _session(driver)

    act = next(a for a in build_show_acts(15) if a.id == "ww_werewolf")
    assert act.light.dark_ms > 0
    assert act.audio_delay_ms == act.light.enter_ms, "소리와 조명이 따로 논다"

    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {"act": act.id}})

    # 암전 구간: 색이 아직 오르면 안 된다.
    await asyncio.sleep(act.light.enter_ms / 1000 * 0.7)
    assert driver.last[1] == 0, "암전을 거치지 않았다"

    await asyncio.sleep(act.light_ms / 1000 + 0.4)
    assert driver.last[0] == act.light.scene.color
    assert driver.last[1] == act.light.scene.brightness


@pytest.mark.asyncio
async def test_밤_색은_말이_끝나면_물러난다() -> None:
    """말이 끝났는데 방이 계속 붉으면 그때부터는 연출이 아니라 그냥 붉은 방이다.

    되돌리는 시점을 시간으로 재지 않는 이유: 앞에 깔리는 효과음 길이를 백엔드가
    모른다(mp3). 실제로 말이 끝난 시점은 태블릿만 알고, 그걸 재생 완료 통보로
    보내준다. 그 신호를 쓴다.
    """
    driver = MockDriver()
    session, _ = _session(driver)
    audio = AudioManager(_ExplodingEngine())  # type: ignore[arg-type]
    sent: list[WSMessage] = []

    async def collect(msg: WSMessage) -> None:
        sent.append(msg)

    audio.attach_broadcast(collect)
    session._audio = audio

    act = next(a for a in build_show_acts(15) if a.id == "ww_werewolf")
    assert act.light.rest is not None

    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {"act": act.id}})
    await asyncio.sleep(act.light_ms / 1000 + 0.4)
    assert driver.last[1] == act.light.scene.brightness, "밤 색이 안 올라왔다"

    # 태블릿인 척: 효과음 끝 → 목소리 끝.
    for _ in range(2):
        pending = [m for m in sent if m.msg_type in ("sfx_play", "tts_play")][-1]
        await session.handle_client_message(
            {
                "input_type": "audio_ack",
                "data": {"playback_id": pending.payload["playback_id"], "status": "played"},
            }
        )
        await _settle()
    await asyncio.sleep(0.3)

    assert driver.last[0] == act.light.rest.color
    assert driver.last[1] == act.light.rest.brightness, "말이 끝났는데 방이 붉게 남았다"


@pytest.mark.asyncio
async def test_요트_재현은_바탕_위에_얹혔다_스스로_돌아온다() -> None:
    """요트 연출은 "백색 인식 조명 위에서 잠깐 물들었다 돌아온다"가 전부다.

    콘솔의 바탕도 같은 백색이라 큐만 얹으면 실제 게임과 똑같이 보인다. 앞뒤로
    무엇을 덧붙이면 게임에 없는 연출이 된다.
    """
    driver = MockDriver()
    session, _ = _session(driver)

    act = next(a for a in build_show_acts(15) if a.id == "yacht_score")
    assert act.light.cue is not None
    assert act.light.dark_ms == 0, "요트는 재우지 않는다"
    assert act.light.rest is None, "큐는 스스로 제자리로 돌아온다"
    assert act.audio_delay_ms == 0, "요트는 소리가 곧바로 나가야 한다"

    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {"act": act.id}})
    await asyncio.sleep(act.light_ms / 1000 + 0.5)

    colors = [c for c, _b, _d in driver.applied]
    assert act.light.cue.color in colors, "연출 색이 아예 안 나갔다"
    assert driver.last[0] == NEUTRAL_SCENE.color, "큐가 끝났는데 백색으로 안 돌아왔다"
    assert driver.last[1] == NEUTRAL_SCENE.brightness


@pytest.mark.asyncio
async def test_전략_조언은_조명을_건드리지_않는다() -> None:
    """실제 게임에서 전략 조언에는 조명 큐가 없다. 굴림 결과를 보고 얹는 말이라
    사건이 아니고, 요트 구간은 백색 인식 조명이 유지되어야 한다. 여기서 없는
    연출을 만들어 붙이면 발표에서 보여준 것과 실물이 달라진다."""
    driver = MockDriver()
    session, _ = _session(driver)

    act = next(a for a in build_show_acts(15) if a.id == "strategy")
    assert act.persona_id == "chungcheong"
    assert act.sfx == "dice_recognized"
    assert act.light.cue is None and act.light.dark_ms == 0

    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {"act": act.id}})
    await asyncio.sleep(act.light_ms / 1000 + 0.4)

    # 나간 명령이 있다면 전부 요트 인식 조명(백색 100%)이어야 한다.
    # 암전도, 색이 물드는 것도 없다.
    for color, brightness, _duration in driver.applied:
        assert color == NEUTRAL_SCENE.color, f"전략 조언인데 색이 바뀌었다: {color}"
        assert brightness == NEUTRAL_SCENE.brightness, "전략 조언인데 밝기가 바뀌었다"


@pytest.mark.asyncio
async def test_없는_연출_이름은_무시된다_발표() -> None:
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {"act": "없음"}})
    await session.handle_client_message({"input_type": "CONTROL_SHOW", "data": {}})
    await _settle()

    assert not driver.applied


@pytest.mark.asyncio
async def test_접속하면_발표_연출_목록도_알려준다() -> None:
    driver = MockDriver()
    session, sock = _session(driver)

    await session.send_hello()

    payload = sock.sent[0]["payload"]
    acts = payload["acts"]
    assert {a["id"] for a in acts} == {a.id for a in build_show_acts()}
    for act in acts:
        assert act["label"] and act["text"] and act["persona"]
        # 버튼을 잠가 두는 시간이다. 0이면 누르자마자 풀려 연달아 눌린다.
        assert act["duration_ms"] > 0
        # 효과음과 목소리를 겹치는 시점. 화면이 이 값으로 재생 완료를 앞당긴다.
        assert act["voice_overlap_ms"] > 0


@pytest.mark.asyncio
async def test_콘솔_바탕은_로비와_같은_백색이다() -> None:
    """관리자 화면에 들어갔다는 이유로 방 조명이 달라지면, 발표자는 아무것도
    안 했는데 무대가 먼저 바뀐다.

    색온도까지 같아야 한다. 백색을 RGB로 내면 전구마다 흰색이 갈리는데(§색온도)
    로비는 색온도로 내고 있어서, 여기만 RGB로 내면 두 화면의 흰색이 달라진다.
    """
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message({"input_type": "CONTROL_SHOW_REST", "data": {}})
    await _settle()

    color, brightness, _duration, kelvin = driver.calls[-1]
    assert brightness == NEUTRAL_SCENE.brightness
    assert color == NEUTRAL_SCENE.color
    assert kelvin == NEUTRAL_SCENE.kelvin, "백색을 RGB로 내면 전구마다 흰색이 갈린다"


@pytest.mark.asyncio
async def test_소등은_같은_자리에서_불만_끈다() -> None:
    """소등을 풀면 원래 백색으로 돌아와야 한다. 색까지 바뀌어 있으면
    껐다 켠 것이 아니라 다른 조명이 된다."""
    driver = MockDriver()
    session, _ = _session(driver)

    await session.handle_client_message({"input_type": "CONTROL_SHOW_REST", "data": {"dark": True}})
    await _settle()
    assert driver.last[1] == 0

    await session.handle_client_message(
        {"input_type": "CONTROL_SHOW_REST", "data": {"dark": False}}
    )
    await _settle()

    color, brightness, _duration, kelvin = driver.calls[-1]
    assert (color, brightness, kelvin) == (
        NEUTRAL_SCENE.color,
        NEUTRAL_SCENE.brightness,
        NEUTRAL_SCENE.kelvin,
    )


def test_발표_음원이_지금_문장과_맞는다() -> None:
    """문장을 고치고 음원을 다시 안 만들면 자막과 목소리가 다른 말을 한다.

    발표장에서 처음 알게 되면 늦다. 고쳤으면 아래를 돌린다.

        python3 tools/generate_show_voices.py

    음원이 **아직 없는** 것은 여기서 잡지 않는다. 그건 어긋남이 아니라 아직
    만들지 않은 것이고, 화면이 버튼마다 표시한다(아래 테스트).
    """
    stale = []
    for act in build_show_acts():
        stamp = act.voice_path.with_suffix(".txt")
        if not act.voice_path.exists() or not stamp.exists():
            continue
        if json.loads(stamp.read_text(encoding="utf-8"))["text"] != act.text:
            stale.append(act.id)
    assert not stale, "음원을 다시 만드세요 (tools/generate_show_voices.py): " + ", ".join(stale)


@pytest.mark.asyncio
async def test_음원이_없는_연출은_화면에_표시된다() -> None:
    """음원이 없으면 조명과 자막만 나간다. 그 사실을 발표장에서 처음 알면 늦다.

    조용히 넘어가는 것이 제일 나쁘다 — 눌렀는데 말이 없으면 고장으로 보인다.
    """
    driver = MockDriver()
    session, sock = _session(driver)

    await session.send_hello()
    acts = sock.sent[0]["payload"]["acts"]

    by_id = {a.id: a for a in build_show_acts()}
    for entry in acts:
        assert (
            entry["has_voice"] == by_id[entry["id"]].voice_path.exists()
        ), f"{entry['id']}: 음원 유무가 화면에 잘못 전달됐다"
