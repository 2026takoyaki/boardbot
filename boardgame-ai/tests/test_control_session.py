"""컨트롤 세션 — 조명·소리를 직접 다루는 자리.

게임이 아니라서 FSM도 비전도 없다. 여기서 지키는 것은 셋이다.

  - 사용자가 고른 밝기가 **그대로** 나간다 (다른 컨텍스트의 하한에 걸리지 않는다)
  - 연출이 끝나면 **사용자가 맞춰 둔 색**으로 돌아온다 (중립이 아니라)
  - 이상한 입력이 들어와도 죽지 않는다
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from backend.control_session import ControlSession
from bulb.config import LightConfig
from bulb.controller import LightController
from bulb.driver.mock import MockDriver
from bulb.scenes import CONTROL_CUES, NEUTRAL_SCENE


class _FakeSocket:
    """보낸 것을 모아두는 가짜 소켓."""

    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    async def send_json(self, data: dict[str, Any]) -> None:
        self.sent.append(data)


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
