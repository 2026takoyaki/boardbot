"""컨트롤 세션 — 진행자가 조명과 소리를 직접 다루는 자리.

요트·늑대인간과 같은 급으로 로비에서 들어오고 나간다. 다른 점은 **게임이 아니라
조명 자체가 다루는 대상**이라는 것이다. FSM도, 비전도, 에이전트도 없다.

하는 일은 셋이다.

    바탕 조명 조절   슬라이더로 색과 밝기를 직접 정한다
    연출 버튼        조명 큐 + 효과음을 함께 터뜨린다 (축하·약올리기·박수·방구·파티)
    발표 연출        게임의 한 순간을 통째로 재현한다 (backend/show_acts.py)

앞의 둘은 컨트롤 화면이, 마지막 하나는 관리자 콘솔이 쓴다. 화면은 둘인데 세션이
하나인 이유: 둘 다 "조명과 소리를 직접 부린다"는 같은 일을 하고, 특히 **나갈 때
조명을 되돌리는 경로**가 같기 때문이다. 세션을 따로 파면 그 복구 경로가 두 벌이
되고, 한쪽만 고치면 발표장에서 방이 붉은 채로 남는다.

나갈 때 원래대로 돌린다. 이건 세션이 스스로 하지 않고 서버의 finally가 한다 —
사용자가 나가기를 누르든, 탭을 닫든, 네트워크가 끊기든 **연결이 끊어지는 모든
경로**에서 조명이 복구되어야 하기 때문이다. 나가기 버튼에만 걸어두면 탭을 닫은
순간 방이 파티 색으로 남는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Iterable
from dataclasses import replace
from typing import Any

from fastapi import WebSocket

from audio.manager import AudioManager
from backend.show_acts import ShowAct, build_show_acts
from bulb.controller import LightController
from bulb.scenes import CONTROL_CUES, NEUTRAL_SCENE, SHOW_REST_SCENE, Scene
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
        show_acts: Iterable[ShowAct] | None = None,
    ) -> None:
        self.websocket = websocket
        self._audio = audio_manager
        self._light = light_controller
        # 발표 연출 목록. 서버가 조명 설정(야간 밝기)에 맞춰 만들어 넘긴다.
        # 안 넘기면 환경 기본값으로 만든다 — 테스트가 조명 설정을 몰라도 된다.
        self._acts: dict[str, ShowAct] = {
            act.id: act for act in (show_acts if show_acts is not None else build_show_acts())
        }
        # 지금 도는 발표 연출의 목소리. 이게 끝나면 조명이 물러난다.
        # 슬롯 하나뿐인 이유: 연출은 한 번에 하나만 돌고, 새 연출이 시작되면
        # 옛 목소리의 뒤늦은 통보가 새 색을 지워선 안 된다.
        self._voice_id: str | None = None
        self._voice_rest: Scene | None = None
        self._show_task: asyncio.Task[None] | None = None
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
                    # 발표 연출. 자막(text)까지 같이 보낸다 — 관리자 콘솔은
                    # 발표자가 보는 화면이라, 무엇이 나갈지 누르기 전에 읽혀야 한다.
                    "acts": [
                        {
                            "id": a.id,
                            "label": a.label,
                            "hint": a.hint,
                            "text": a.text,
                            "persona": a.persona_name,
                            "duration_ms": a.duration_ms(),
                            # 효과음 끝나기 이만큼 전에 목소리를 부른다.
                            # 겹치는 일은 화면이 한다 — 아래 _play_show 참고.
                            "voice_overlap_ms": a.voice_overlap_ms,
                            # 음원이 아직 없으면 조명과 자막만 나간다. 화면이
                            # 그 사실을 표시할 수 있게 알려준다.
                            "has_voice": a.voice_path.exists(),
                        }
                        for a in self._acts.values()
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
                self._on_voice_done(pbid)
            return

        if input_type == "CONTROL_SET_LIGHT":
            await self._set_light(payload)
            return

        if input_type == "CONTROL_CUE":
            await self._play_cue(payload)
            return

        if input_type == "CONTROL_SHOW":
            await self._play_show(payload)
            return

        if input_type == "CONTROL_SHOW_REST":
            self._show_rest(bool(payload.get("dark", False)))
            return

    async def restore_light(self) -> None:
        """나갈 때 조명을 원래대로. 서버의 finally가 부른다."""
        # 암전을 기다리던 연출이 있으면 여기서 끊는다. 나간 뒤에 늑대가 울면
        # 로비로 돌아간 화면 위로 소리만 남는다.
        if self._show_task is not None and not self._show_task.done():
            self._show_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._show_task
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

    async def _play_show(self, payload: dict[str, Any]) -> None:
        """발표 연출 하나 — 조명·효과음·목소리를 함께.

        조명은 기다리지 않고 던진다(요트 재현은 앞뒤 백색까지 6초가 넘는다).
        소리는 효과음이 먼저, 목소리가 뒤다. 같은 sequence_id로 묶어 순서를
        못 박는다 — 뒤집히면 늑대 울음이 멘트를 자르고 들어온 것처럼 들린다.

        **둘이 겹치는 시점은 화면이 정한다.** 이 큐는 한 번에 하나만 재생하고
        (태블릿이 Audio 하나를 돌려쓴다) 다음 항목은 재생 완료 통보를 받아야
        나가는데, 관리자 콘솔은 효과음이 끝나기 전에 그 통보를 보내 목소리를
        일찍 끌어온다. 순서와 내용의 주인은 여전히 여기다.

        둘 다 interruptible=False다. 발표자가 누른 것이라 무슨 일이 있어도
        끝까지 나가야 한다.
        """
        act = self._acts.get(str(payload.get("act", "")))
        if act is None:
            return

        # 이전 연출의 목소리가 아직 안 끝났다면 그 통보는 무시해야 한다.
        # 안 그러면 뒤늦게 도착해 새 연출의 색을 백색으로 지운다.
        self._voice_id = None
        self._voice_rest = None

        if self._light is not None:
            self._light.play_show(act.light, game="control")

        if self._audio is None:
            return
        # 소리는 조명이 색을 올리기 시작할 때 들어온다. 암전을 두는 연출에서는
        # 그만큼 늦는다 — 캄캄해지기도 전에 늑대가 울면 어둠이 연출로 안 읽힌다.
        #
        # 기다리는 동안 이 소켓의 수신 루프가 멈추면 안 되므로 따로 돌린다.
        if self._show_task is not None and not self._show_task.done():
            self._show_task.cancel()
        self._show_task = asyncio.create_task(self._speak_act(act))

    async def _speak_act(self, act: ShowAct) -> None:
        assert self._audio is not None
        if act.audio_delay_ms > 0:
            await asyncio.sleep(act.audio_delay_ms / 1000)
        sequence_id = f"show_{act.id}_{uuid.uuid4().hex[:6]}"
        if act.sfx:
            await self._audio.enqueue_sfx(
                act.sfx, sequence_id=sequence_id, seq_index=0, interruptible=False
            )
        playback_id = await self._audio.enqueue_tts(
            text=act.text,
            # 합성하지 않는다. 미리 만들어 둔 파일을 그대로 튼다.
            audio_url=act.voice_url,
            sequence_id=sequence_id,
            seq_index=1,
            interruptible=False,
        )
        # 이 목소리가 끝나면 조명이 물러난다(연출에 물러날 자리가 있다면).
        self._voice_id = playback_id
        self._voice_rest = act.light.rest

    def _show_rest(self, dark: bool) -> None:
        """콘솔의 바탕으로 되돌린다. dark면 같은 자리에서 불만 끈다.

        슬라이더 경로(CONTROL_SET_LIGHT)를 쓰지 않는 이유는 색온도다. 저쪽은
        사용자가 고른 RGB를 그대로 싣느라 색온도를 버리는데, 백색을 RGB로 내면
        전구마다 흰색이 다르게 보인다(bulb/scenes.py §색온도). 로비와 같은
        백색이 목적이면 로비와 같은 방식으로 내야 한다.
        """
        # 물러나던 중이었다면 그 통보는 이제 의미가 없다. 안 지우면 뒤늦게
        # 도착해 방금 사람이 고른 상태를 덮어쓴다.
        self._voice_id = None
        self._voice_rest = None
        if self._light is None:
            return
        scene = (
            replace(SHOW_REST_SCENE, name="show_dark", brightness=0) if dark else SHOW_REST_SCENE
        )
        self._light.settle(scene, game="control")

    def _on_voice_done(self, playback_id: str) -> None:
        """발표 연출의 목소리가 끝났다 → 조명을 바탕으로 되돌린다.

        시간을 재서 되돌리지 않는 이유: 앞에 깔리는 효과음 길이를 백엔드가
        모른다(mp3라 헤더를 읽어야 하고, 목소리가 그 위에 얼마나 겹칠지는 그
        길이에 달렸다). 실제로 말이 끝난 시점은 태블릿만 아는데, 그걸 이미
        재생 완료 통보로 보내주고 있다. 추측 대신 그 신호를 쓴다.
        """
        if playback_id != self._voice_id:
            return
        rest, self._voice_rest, self._voice_id = self._voice_rest, None, None
        if rest is not None and self._light is not None:
            self._light.settle(rest, game="control")

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
