"""컨트롤 세션 — 진행자가 조명과 소리를 직접 다루는 자리.

요트·늑대인간과 같은 급으로 로비에서 들어오고 나간다. 다른 점은 **게임이 아니라
조명 자체가 다루는 대상**이라는 것이다. FSM도, 비전도, 에이전트도 없다.

하는 일은 둘뿐이다.

    바탕 조명 조절   슬라이더로 색과 밝기를 직접 정한다
    연출 버튼        조명 큐 + 효과음을 함께 터뜨린다 (축하·약올리기·박수·방구·파티)

나갈 때 원래대로 돌린다. 이건 세션이 스스로 하지 않고 서버의 finally가 한다 —
사용자가 나가기를 누르든, 탭을 닫든, 네트워크가 끊기든 **연결이 끊어지는 모든
경로**에서 조명이 복구되어야 하기 때문이다. 나가기 버튼에만 걸어두면 탭을 닫은
순간 방이 파티 색으로 남는다.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import WebSocket

from audio.manager import AudioManager
from bulb.controller import LightController
from bulb.scenes import CONTROL_CUES, NEUTRAL_SCENE
from core.constants import MsgType
from core.envelope import WSMessage

logger = logging.getLogger(__name__)

# 0까지 내릴 수 있다. 소등도 연출의 하나다 — 늑대인간 밤이 암전에서 시작하듯,
# 진행자가 방을 완전히 끄고 싶은 순간이 있다.
#
# 방이 캄캄해져도 조작은 계속된다. 태블릿 화면은 전구와 별개로 켜져 있고,
# 슬라이더를 다시 올리면 그대로 돌아온다.
_MIN_BRIGHTNESS = 0
_MAX_BRIGHTNESS = 100

# 전환 시간 상한. 이보다 길면 슬라이더를 놓고 한참 뒤에야 색이 도착해
# 조작이 안 먹는 것으로 보인다. 전구 쪽도 긴 페이드 중에 새 명령이 오면
# 이전 것을 버리므로 실익이 없다.
_MAX_FADE_MS = 8000


def _clamp_channel(v: Any) -> int:
    try:
        return max(0, min(255, int(v)))
    except (TypeError, ValueError):
        return 0


class ControlSession:
    """조명·소리 직접 제어. 연결 하나당 하나."""

    def __init__(
        self,
        websocket: WebSocket,
        audio_manager: AudioManager | None = None,
        light_controller: LightController | None = None,
    ) -> None:
        self.websocket = websocket
        self._audio = audio_manager
        self._light = light_controller
        self._send_raw_bound = self._send_raw
        if audio_manager is not None:
            audio_manager.attach_broadcast(
                self._send_raw_bound, session_id=audio_manager.get_session_id()
            )

    # ── 공개 ─────────────────────────────────────────────────────────────────

    async def send_hello(self) -> None:
        """접속 인사. 화면이 버튼을 그릴 수 있도록 연출 목록을 함께 준다.

        목록의 주인은 백엔드다(bulb/scenes.py). 프론트가 자기 목록을 갖고 있으면
        연출을 하나 추가할 때 두 곳을 고쳐야 하고, 한쪽만 고치면 눌러도 아무 일이
        없는 버튼이 생긴다.
        """
        await self.send(
            WSMessage.make_hello(
                {
                    "game_type": "control",
                    "cues": [
                        {"id": c.name, "label": c.label, "duration_ms": c.total_ms}
                        for c in CONTROL_CUES.values()
                    ],
                    "default_light": {
                        "color": list(NEUTRAL_SCENE.color),
                        "brightness": NEUTRAL_SCENE.brightness,
                    },
                    "brightness_range": [_MIN_BRIGHTNESS, _MAX_BRIGHTNESS],
                    "max_fade_ms": _MAX_FADE_MS,
                }
            )
        )

    async def handle_client_message(self, data: dict[str, Any]) -> None:
        input_type = str(data.get("input_type", ""))
        payload = dict(data.get("data", {}))

        # 오디오 재생 끝/중단 통보. 큐 진행 트리거 — 다른 세션과 동일하다.
        if input_type == "audio_ack" and self._audio is not None:
            pbid = str(payload.get("playback_id", ""))
            status = str(payload.get("status", ""))
            if pbid:
                await self._audio.handle_ack(pbid, status)
            return

        if input_type == "CONTROL_SET_LIGHT":
            await self._set_light(payload)
            return

        if input_type == "CONTROL_CUE":
            await self._play_cue(payload)
            return

    async def restore_light(self) -> None:
        """나갈 때 조명을 원래대로. 서버의 finally가 부른다."""
        if self._light is None:
            return
        try:
            await self._light.reset()
        except Exception:
            # 조명 정리가 실패해도 세션 종료를 막지 않는다.
            logger.warning("control: 조명 복구 실패", exc_info=True)

    # ── 내부 ─────────────────────────────────────────────────────────────────

    async def _set_light(self, payload: dict[str, Any]) -> None:
        raw = payload.get("color")
        if not isinstance(raw, list | tuple) or len(raw) != 3:
            return
        color = (_clamp_channel(raw[0]), _clamp_channel(raw[1]), _clamp_channel(raw[2]))
        try:
            brightness = int(payload.get("brightness", NEUTRAL_SCENE.brightness))
        except (TypeError, ValueError):
            brightness = NEUTRAL_SCENE.brightness
        brightness = max(_MIN_BRIGHTNESS, min(_MAX_BRIGHTNESS, brightness))

        # 새 값까지 몇 초에 걸쳐 물들일지. 화면이 정한다 — 즉시 바꾸는 것과
        # 서서히 바꾸는 것은 연출로서 전혀 다른 물건이라 사람이 골라야 한다.
        try:
            fade_ms = int(payload.get("duration_ms", 0))
        except (TypeError, ValueError):
            fade_ms = 0
        fade_ms = max(0, min(_MAX_FADE_MS, fade_ms))

        if self._light is not None:
            # game="control"로 넘긴다. 이 컨텍스트의 밝기 하한은 0이라(bulb/config.py)
            # 사용자가 고른 값이 그대로 나간다. game=None으로 넘기면 "모르는
            # 컨텍스트" 취급을 받아 하한 60%에 걸리고, 어둡게 내려도 방이 안 어두워진다.
            await self._light.apply_manual(color, brightness, game="control", duration_ms=fade_ms)

        # 화면의 조명 띠도 같은 값을 그리도록 되돌려 보낸다. 실제 전구가 없어도
        # (드라이버가 mock이어도) 화면에서는 조작이 먹는 것으로 보여야 한다.
        await self.send(
            WSMessage(
                msg_type=MsgType.LIGHT_STATE.value,
                payload={
                    "color": list(color),
                    "brightness": brightness,
                    # 화면 가장자리 색 띠도 같은 시간에 걸쳐 바뀌어야 방과 어긋나지 않는다.
                    "duration_ms": fade_ms,
                },
            )
        )

    async def _play_cue(self, payload: dict[str, Any]) -> None:
        cue = CONTROL_CUES.get(str(payload.get("cue", "")))
        if cue is None:
            return
        if self._light is not None:
            # 즉시 반환한다. 파티는 10초짜리라 기다리면 그동안 버튼이 죽는다.
            self._light.play_control_cue(cue, game="control")
        if self._audio is not None:
            await self._audio.enqueue_sfx(cue.sfx)

    # ── 송신 ─────────────────────────────────────────────────────────────────

    async def send(self, message: WSMessage) -> None:
        await self._send_raw(message)

    async def _send_raw(self, message: WSMessage) -> None:
        """이 세션이 내보내는 모든 메시지가 지나가는 곳.

        AudioManager가 합성을 끝내고 다시 부르는 콜백이기도 하다. 그쪽은
        **dict가 아니라 WSMessage를 넘긴다** — 다른 세션들과 같은 규약이다.
        """
        try:
            await self.websocket.send_json(message.to_dict())
        except Exception:
            # 이미 끊긴 소켓. 조명 복구는 서버 finally가 따로 한다.
            logger.debug("control: 송신 실패 (연결 종료됨)")
