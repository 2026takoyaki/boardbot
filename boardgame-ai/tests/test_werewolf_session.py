"""WerewolfSession의 클라이언트 메시지 처리 — 특히 게임 나가기 경로.

로비·좌석 등록·늑대인간이 같은 웹소켓(/ws/tablet)을 계속 쓰므로, 게임에서
나갈 때 진행 중이던 TTS를 끊지 않으면 로비 화면 위로 게임 멘트가 이어서
흘러나온다. RESTART/reset_game 핸들러가 이걸 막는지 확인한다.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from audio.manager import AudioManager
from audio.tts_engine import TTSEngine
from backend.werewolf_session import WerewolfSession


class FakeWebSocket:
    def __init__(self) -> None:
        self.sent: list[dict] = []

    async def send_json(self, data: dict) -> None:
        self.sent.append(data)


def _make_audio_manager() -> AudioManager:
    engine = MagicMock(spec=TTSEngine)
    engine.cache_hit = MagicMock(return_value=Path("/cache/tts/static/fake.wav"))
    engine.synthesize = AsyncMock(return_value=Path("/cache/tts/static/fake.wav"))
    engine.is_available = MagicMock(return_value=True)
    return AudioManager(engine)


def _make_session(ws: FakeWebSocket, audio_manager: AudioManager) -> WerewolfSession:
    return WerewolfSession(
        ws,
        send_fusion_context_fn=lambda ctx, state_version: None,
        loop=asyncio.get_running_loop(),
        audio_manager=audio_manager,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("input_type", ["RESTART", "reset_game"])
async def test_나가기는_재생_중이거나_대기_중인_안내를_끊는다(input_type):
    ws = FakeWebSocket()
    audio_manager = _make_audio_manager()
    session = _make_session(ws, audio_manager)

    # 첫 항목은 큐가 비어 있어 곧바로 재생 중(_current)이 된다.
    await audio_manager.enqueue_tts("지금 재생 중인 안내.")
    # 두 번째는 뒤에서 대기한다.
    await audio_manager.enqueue_tts("큐에서 대기 중인 다음 안내.")
    assert audio_manager._current is not None
    assert audio_manager._queue

    await session.handle_client_message({"input_type": input_type, "data": {}})

    assert audio_manager._current is None, "재생 중이던 안내가 끊기지 않았다"
    assert not audio_manager._queue, "대기 중이던 안내가 큐에 남아 로비까지 흘러간다"
    kinds = [m["msg_type"] for m in ws.sent]
    assert "tts_interrupt" in kinds, "프론트에 인터럽트 신호가 가지 않았다"
