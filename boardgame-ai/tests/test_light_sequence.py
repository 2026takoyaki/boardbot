"""색 시퀀스와 전구 재탐색.

실물 전구는 분당 약 60개 명령에서 끊고(client quota exceeded), 흐름 하나에
전환을 16개 남짓밖에 받지 않는다(2026-11-11 실측). 여기서는 그 두 제약을
지키는 경로를 하드웨어 없이 검증한다.
"""

from __future__ import annotations

import asyncio

import pytest

from bulb import LightConfig, build_controller, discovery, driver_ips, reconnect
from bulb.controller import LightController
from bulb.driver.base import (
    MAX_FLOW_TRANSITIONS,
    SequenceStep,
    flow_period,
    flow_transition_count,
    plan_flows,
)
from bulb.driver.mock import MockDriver
from bulb.driver.multi import MultiDriver
from bulb.scenes import CONTROL_CUES, FINALE_FANFARE, GOLD_BURST, NEUTRAL_SCENE

_ALL_SEQUENCE_CUES = [*CONTROL_CUES.values(), GOLD_BURST, FINALE_FANFARE]


# ── 흐름 접기 ────────────────────────────────────────────────────────────────


def test_flow_period_folds_repeats() -> None:
    a = SequenceStep((255, 0, 0), 100, 100)
    b = SequenceStep((0, 255, 0), 100, 100)
    assert flow_period([a, b, a, b, a, b]) == ((a, b), 3)


def test_flow_period_keeps_non_repeating() -> None:
    a = SequenceStep((255, 0, 0), 100, 100)
    b = SequenceStep((0, 255, 0), 100, 100)
    c = SequenceStep((255, 0, 0), 300, 100)
    assert flow_period([a, b, c]) == ((a, b, c), 1)


@pytest.mark.parametrize("cue", _ALL_SEQUENCE_CUES, ids=lambda c: c.name)
def test_every_flow_chunk_fits(cue) -> None:
    """묶음 하나라도 전구 한도를 넘기면 실물에서 invalid command로 통째로 죽는다."""
    for _offset, chunk, alt in plan_flows(cue.sequence(), cue.alt_sequence()):
        for seq in (chunk, alt):
            if seq is None:
                continue
            period, _ = flow_period(seq)
            assert sum(flow_transition_count(s) for s in period) <= MAX_FLOW_TRANSITIONS


@pytest.mark.parametrize("cue", _ALL_SEQUENCE_CUES, ids=lambda c: c.name)
def test_every_cue_needs_few_commands(cue) -> None:
    """분당 약 60개 제한. 연출 하나가 명령 몇 개 이상을 쓰면 연달아 누를 수 없다."""
    assert len(plan_flows(cue.sequence(), cue.alt_sequence())) <= 3


def test_gold_burst_bulbs_shimmer_in_opposite_phase() -> None:
    """한쪽이 밝을 때 다른 쪽이 어둡다 — 빛이 두 전구 사이를 오간다."""
    main, alt = GOLD_BURST.sequence(), GOLD_BURST.alt_sequence()
    assert alt is not None
    shimmer = [(a.brightness, b.brightness) for a, b in zip(main, alt, strict=True)][1:-1]
    assert shimmer and all(x != y for x, y in shimmer)


def test_finale_hits_land_on_sfx_beats() -> None:
    """game_end.mp3의 음 시작(0.6, 1.7, 2.7, 3.35초)에 밝기 100으로 터진다."""
    t = 0
    peaks = []
    for step in FINALE_FANFARE.sequence():
        if step.brightness == 100 and step.hold_ms <= 80:
            peaks.append(t)
        t += step.hold_ms
    for beat in (600, 1700, 2700, 3350):
        assert beat in peaks


def test_plan_flows_rejects_alt_with_different_rhythm() -> None:
    a = SequenceStep((255, 0, 0), 100, 100)
    b = SequenceStep((0, 255, 0), 200, 100)
    with pytest.raises(ValueError):
        plan_flows([a], [b])


# ── 컨트롤러 ─────────────────────────────────────────────────────────────────


def _controller(driver: MockDriver) -> LightController:
    return LightController(driver, LightConfig(driver="mock"))


@pytest.mark.asyncio
async def test_sequence_driver_gets_one_call_then_returns_to_scene() -> None:
    driver = MockDriver(sequence=True)
    ctl = _controller(driver)
    await ctl.start()
    driver.applied.clear()

    party = CONTROL_CUES["party"]
    await ctl._run_control_cue(party, "control")

    # 시퀀스는 한 번에 통째로, 단계별 apply는 없다.
    assert len(driver.sequences) == 1
    assert driver.sequences[0][0] == party.sequence()
    # 끝나면 바탕으로 돌아온다. 같은 백색이어도 반드시 다시 보낸다 — 전구는
    # 시퀀스의 마지막 색(보라)에 머물러 있다.
    back = (NEUTRAL_SCENE.color, NEUTRAL_SCENE.brightness, party.fall_ms)
    assert driver.applied == [back]


@pytest.mark.asyncio
async def test_step_driver_still_walks_steps() -> None:
    """화면 조명 드라이버는 그대로 단계별로 그린다."""
    driver = MockDriver()
    ctl = _controller(driver)
    await ctl.start()
    driver.applied.clear()

    cue = CONTROL_CUES["celebrate"]
    await ctl._run_control_cue(cue, "control")

    assert driver.sequences == []
    assert len(driver.applied) == len(cue.steps) + 1


@pytest.mark.asyncio
async def test_show_plays_sequence_after_scene() -> None:
    from backend.show_acts import build_show_acts

    act = next(a for a in build_show_acts(15) if a.id == "yacht_legend")
    driver = MockDriver(sequence=True)
    ctl = _controller(driver)
    ctl._last_applied = None
    await ctl._run_show(act.light, "control")
    plans = plan_flows(GOLD_BURST.sequence(), GOLD_BURST.alt_sequence())
    assert [s[0] for s in driver.sequences] == [chunk for _o, chunk, _a in plans]
    # 두 번째 전구 몫도 함께 간다.
    assert driver.alts == [alt for _o, _c, alt in plans]


@pytest.mark.asyncio
async def test_long_sequence_chunks_are_sent_on_time(monkeypatch) -> None:
    """피날레처럼 나뉜 연출은 뒤 묶음을 그 묶음의 시작 시각에 보낸다."""
    driver = MockDriver(sequence=True)
    ctl = _controller(driver)
    loop = asyncio.get_running_loop()
    sent_at: list[float] = []
    original = driver.play_sequence

    async def timed(steps, brightness, alt=None):
        sent_at.append(loop.time())
        await original(steps, brightness, alt)

    monkeypatch.setattr(driver, "play_sequence", timed)
    await ctl._play_flows(FINALE_FANFARE, "control")

    plans = plan_flows(FINALE_FANFARE.sequence(), FINALE_FANFARE.alt_sequence())
    offsets = [o for o, _c, _a in plans]
    assert len(sent_at) == len(offsets) >= 2
    gap = (sent_at[1] - sent_at[0]) * 1000
    assert abs(gap - (offsets[1] - offsets[0])) < 60


@pytest.mark.asyncio
async def test_multi_driver_needs_all_children_for_sequence() -> None:
    assert MultiDriver([MockDriver(sequence=True), MockDriver(sequence=True)]).supports_sequence
    assert not MultiDriver([MockDriver(sequence=True), MockDriver()]).supports_sequence


@pytest.mark.asyncio
async def test_swap_driver_reapplies_scene() -> None:
    old, new = MockDriver(), MockDriver()
    ctl = _controller(old)
    await ctl.start()
    await ctl.swap_driver(new)
    assert old.closed
    assert new.applied and new.applied[-1][0] == NEUTRAL_SCENE.color


# ── 재탐색 ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reconnect_skips_when_not_real_bulbs() -> None:
    ctl = build_controller(config=LightConfig(driver="mock"))
    status = await reconnect(ctl)
    assert status["ok"] is False
    assert status["driver"] == "mock"


@pytest.mark.asyncio
async def test_reconnect_swaps_to_discovered_ips(monkeypatch) -> None:
    pytest.importorskip("yeelight")
    ctl = build_controller(
        config=LightConfig(driver="yeelight", bulb_ips=("172.20.10.9", "172.20.10.6"))
    )

    async def fake_locate(hints):
        return ["172.20.10.5", "172.20.10.6"], "discovered"

    swapped = []

    async def fake_swap(driver):
        swapped.append(driver_ips(driver))

    monkeypatch.setattr(discovery, "locate", fake_locate)
    monkeypatch.setattr(ctl, "swap_driver", fake_swap)

    status = await reconnect(ctl)
    assert status == {
        "driver": "yeelight",
        "expected": 2,
        "active": ["172.20.10.5", "172.20.10.6"],
        "source": "discovered",
        "ok": True,
    }
    assert swapped == [["172.20.10.5", "172.20.10.6"]]


@pytest.mark.asyncio
async def test_reconnect_keeps_driver_when_nothing_found(monkeypatch) -> None:
    pytest.importorskip("yeelight")
    ctl = build_controller(config=LightConfig(driver="yeelight", bulb_ips=("172.20.10.5",)))

    async def fake_locate(hints):
        return [], "none"

    monkeypatch.setattr(discovery, "locate", fake_locate)
    before = ctl.driver
    status = await reconnect(ctl)
    assert status["ok"] is False and status["active"] == []
    assert ctl.driver is before


@pytest.mark.asyncio
async def test_locate_uses_configured_when_all_alive(monkeypatch) -> None:
    async def alive(ips):
        return list(ips)

    async def boom(*_a, **_k):
        raise AssertionError("적힌 IP가 다 닿으면 훑지 않는다")

    monkeypatch.setattr(discovery, "probe_all", alive)
    monkeypatch.setattr(discovery, "ssdp", boom)
    monkeypatch.setattr(discovery, "scan", boom)
    assert await discovery.locate(["172.20.10.5"]) == (["172.20.10.5"], "configured")


@pytest.mark.asyncio
async def test_locate_merges_ssdp_and_scan(monkeypatch) -> None:
    async def none_alive(ips):
        return []

    async def via_ssdp(timeout=2.0):
        return ["172.20.10.6"]

    async def via_scan(hints=()):
        return ["172.20.10.5", "172.20.10.6"]

    monkeypatch.setattr(discovery, "probe_all", none_alive)
    monkeypatch.setattr(discovery, "ssdp", via_ssdp)
    monkeypatch.setattr(discovery, "scan", via_scan)
    assert await discovery.locate(["172.20.10.3"]) == (
        ["172.20.10.5", "172.20.10.6"],
        "discovered",
    )


@pytest.mark.asyncio
async def test_probe_closed_port_is_false() -> None:
    # 로컬의 닫힌 포트. 명령 없이 연결만 시도하고 곧바로 실패해야 한다.
    assert await asyncio.wait_for(discovery.probe("127.0.0.1", timeout=0.3), 2) is False
