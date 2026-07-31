"""LightController — 브로드캐스트 스트림을 구독해 조명을 움직인다.

조명 트리거를 TTS/SFX 호출 지점마다 심으면 호출부가 흩어져 유지보수가 어렵고,
어딘가 하나 빠뜨리면 그 페이즈만 조명이 안 바뀐다. 대신 조명을 UI와 같은
계층으로 취급한다 — 프론트엔드가 state_update를 받아 다시 그리듯, 조명도 같은
메시지 스트림을 구독해 선언적으로 반응한다.

    FSM ──WSMessage[]──▶ Session ──┬──▶ Frontend (화면)
                                   └──▶ LightController (조명)

덕분에 games/ 는 조명을 전혀 모르고, 트리거 누락이 원천적으로 생기지 않는다.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Mapping

from bulb.config import LightConfig
from bulb.driver.base import BRIGHTNESS_MAX, RGB, LightDriver
from bulb.scenes import NEUTRAL_SCENE, Cue, Scene
from core.constants import MsgType
from core.envelope import WSMessage

logger = logging.getLogger(__name__)

SceneMap = Mapping[str, Mapping[str, Scene]]
CueMap = Mapping[str, Cue]


class LightController:
    """전구 1개의 Scene/Cue 상태를 관리한다.

    호출자에 대한 약속이 두 가지 있다.

    1. **절대 블로킹하지 않는다.** on_message()는 즉시 반환하고 실제 명령은
       백그라운드로 흐른다. 소켓 지연이 게임 진행을 멈추면 안 된다.
    2. **절대 예외를 던지지 않는다.** 조명 코드가 게임을 깨뜨릴 권한은 없다.
       실패는 로깅만 하고 게임 로직은 계속 간다.
    """

    def __init__(
        self,
        driver: LightDriver,
        config: LightConfig,
        scene_map: SceneMap | None = None,
        cue_map: CueMap | None = None,
    ) -> None:
        self._driver = driver
        self._config = config
        self._scene_map: SceneMap = scene_map if scene_map is not None else {}
        self._cue_map: CueMap = cue_map if cue_map is not None else {}

        self._scene: Scene = NEUTRAL_SCENE
        self._game: str | None = None
        self._phase: str | None = None
        # 마지막으로 전구에 실제로 보낸 값. 같은 값이면 다시 보내지 않는다
        # (Yeelight 분당 명령 수 제한 회피).
        self._last_applied: tuple[RGB, int] | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._cue_task: asyncio.Task[None] | None = None
        self._tasks: set[asyncio.Task[None]] = set()

    # ── 구독 진입점 ──────────────────────────────────────────────────────────

    def on_message(self, message: WSMessage, game: str | None = None) -> None:
        """세션이 프론트로 내보내는 모든 메시지가 여기로도 흐른다.

        Args:
            game: "yacht" | "werewolf" | "lobby". 밝기 하한이 게임마다 다르므로
                (요트는 인식 때문에 어두워질 수 없고 늑대인간은 완전 소등이
                허용된다) 어느 게임인지 알아야 한다.
        """
        if not self._config.enabled:
            return
        try:
            if message.msg_type == MsgType.STATE_UPDATE.value:
                self._on_state_update(message, game)
            elif message.msg_type == MsgType.CUE.value:
                self._on_cue(message, game)
        except Exception:
            # 여기서 예외가 새면 프론트로 나가는 메시지가 막힌다. 절대 안 된다.
            logger.warning("light: on_message 처리 실패", exc_info=True)

    def _on_state_update(self, message: WSMessage, game: str | None) -> None:
        phase = message.payload.get("phase")
        if not isinstance(phase, str):
            return
        # 페이즈가 그대로면 무시. state_update는 페이즈와 무관하게도 자주 온다.
        if (game, phase) == (self._game, self._phase):
            return
        self._game = game
        self._phase = phase
        self._scene = self._resolve_scene(game, phase)
        self._cancel_cue()
        self._spawn(self._apply_scene(self._scene, game))

    def _on_cue(self, message: WSMessage, game: str | None) -> None:
        name = message.payload.get("cue")
        if not isinstance(name, str):
            return
        cue = self._resolve_cue(name, message.payload)
        if cue is None:
            return
        duration_ms = message.payload.get("duration_ms")
        if isinstance(duration_ms, int) and not cue.fits_within(duration_ms):
            # 모달이 닫힌 뒤에도 조명이 색을 물고 있게 된다. 요트에서는 그
            # 상태로 다음 굴림이 들어와 인식이 깨진다.
            logger.warning(
                "light: cue '%s' 길이 %dms가 연출 duration %dms를 넘는다. "
                "복귀가 늦어 인식이 깨질 수 있다.",
                name,
                cue.total_ms,
                duration_ms,
            )
        self._cancel_cue()
        self._cue_task = self._spawn(self._play_cue(cue, game))

    # ── 연출 실행 ────────────────────────────────────────────────────────────

    async def _apply_scene(self, scene: Scene, game: str | None) -> None:
        await self._drive(scene.color, scene.brightness, scene.transition_ms, game)

    async def _play_cue(self, cue: Cue, game: str | None) -> None:
        """터뜨리고 반드시 Scene으로 돌아온다.

        중간에 취소되는 경우는 더 새로운 Cue나 Scene이 들어왔을 때뿐이고,
        그쪽이 곧바로 조명을 다시 몰기 때문에 어중간한 색으로 멈추지 않는다.
        세션이 끊겨 아무것도 뒤따르지 않는 경우는 reset()이 중립으로 되돌린다.
        """
        await self._drive(cue.color, cue.brightness, cue.rise_ms, game)
        # rise는 전구가 알아서 페이드하는 시간이라 우리가 기다려줘야 한다. 안
        # 기다리면 색이 다 오르기도 전에 복귀가 시작돼 total_ms가 실제 복귀
        # 시점보다 길게 잡히고, §2.4 불변식이 근거를 잃는다.
        await asyncio.sleep((cue.rise_ms + cue.hold_ms) / 1000)
        await self._drive(self._scene.color, self._scene.brightness, cue.fall_ms, game)

    async def _drive(
        self,
        color: RGB,
        brightness: int,
        duration_ms: int,
        game: str | None,
    ) -> None:
        level = self._clamp(brightness, game)
        target = (color, level)
        if target == self._last_applied:
            return
        self._last_applied = target
        try:
            await asyncio.wait_for(
                self._driver.apply(color, level, max(0, duration_ms)),
                timeout=self._config.command_timeout_s,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            # 전구가 실제로 어떤 상태인지 모르게 됐다. 캐시를 비워 다음 명령이
            # 중복 제거로 삼켜지지 않게 한다 — 삼켜지는 게 중립 복귀라면
            # 요트 인식이 그대로 깨진다.
            self._last_applied = None
            logger.warning("light: 명령 타임아웃 (rgb=%s brightness=%d)", color, level)
        except Exception:
            self._last_applied = None
            logger.warning("light: 명령 실패 (rgb=%s brightness=%d)", color, level, exc_info=True)

    def _clamp(self, brightness: int, game: str | None) -> int:
        """게임별 밝기 하한 적용.

        늑대인간은 하한이 0이라 완전 소등이 그대로 통과하고, 요트는 하한이 높아
        어두운 값이 들어와도 인식 가능한 밝기로 걷어올려진다. 매핑 테이블이
        실수해도 인식이 죽지 않게 하는 마지막 방어선이다.
        """
        floor = self._config.floor_for(game)
        return max(floor, min(BRIGHTNESS_MAX, brightness))

    def _resolve_cue(self, name: str, payload: dict[str, object]) -> Cue | None:
        """is_highlight가 붙어 있으면 강조 변형을 먼저 찾는다.

        FSM은 큐 이름 하나(yacht_turn_transition)에 is_highlight 플래그를 실어
        보낸다. 연출 강도는 조명 쪽 관심사이므로 이름을 나누지 않고 매핑에서
        갈라낸다 — 변형이 없으면 기본 큐로 떨어지므로 테이블에 없어도 안전하다.
        """
        if payload.get("is_highlight"):
            highlight = self._cue_map.get(f"{name}_highlight")
            if highlight is not None:
                return highlight
        return self._cue_map.get(name)

    def _resolve_scene(self, game: str | None, phase: str) -> Scene:
        """매핑에 없는 페이즈는 중립으로 간다.

        늑대인간 담당자가 페이즈를 추가하거나 이름을 바꿔도 조명이 깨지지 않고,
        로비의 role_registration·card_setup처럼 게임 페이즈 목록에 없는 화면도
        자동으로 밝게 유지된다 (좌석 등록이 비전으로 돌아가는 구간).
        """
        if game is None:
            return NEUTRAL_SCENE
        return self._scene_map.get(game, {}).get(phase, NEUTRAL_SCENE)

    # ── 생명주기 ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """서버 부팅 시 전구를 중립으로 올린다.

        이게 없으면 첫 게임이 시작될 때까지 전구가 이전 상태(꺼져 있거나 지난
        세션의 색) 그대로 남는다. 로비는 orchestrator가 세션을 거치지 않고
        직접 브로드캐스트해서 조명 스트림에 잡히지 않으므로, 좌석 등록 구간의
        밝기는 이 기본값이 유일한 보장이다 (설계문서 §3.5).
        """
        await self.reset()

    async def reset(self) -> None:
        """중립으로 되돌린다. 세션 종료·게임 전환 시 호출.

        다음 세션이 이전 세션의 색을 물려받지 않게 하고, Cue 도중에 연결이
        끊겨 조명이 색을 문 채 멈추는 경우를 정리한다.
        """
        self._cancel_cue()
        self._game = None
        self._phase = None
        self._scene = NEUTRAL_SCENE
        await self._drive(
            NEUTRAL_SCENE.color, NEUTRAL_SCENE.brightness, NEUTRAL_SCENE.transition_ms, None
        )

    async def aclose(self) -> None:
        """프로세스 종료 시 중립 복귀 후 연결 정리."""
        self._cancel_cue()
        for task in list(self._tasks):
            task.cancel()
        with contextlib.suppress(Exception):
            await self.reset()
        with contextlib.suppress(Exception):
            await self._driver.close()

    # ── 태스크 관리 ──────────────────────────────────────────────────────────

    def _cancel_cue(self) -> None:
        if self._cue_task is not None and not self._cue_task.done():
            self._cue_task.cancel()
        self._cue_task = None

    def _spawn(self, coro: object) -> asyncio.Task[None] | None:
        """이벤트 루프에 던지고 즉시 반환. 호출자를 절대 기다리게 하지 않는다."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = self._loop
            if loop is None:
                # 루프가 없으면 실행할 방법이 없다. 코루틴만 정리하고 포기한다.
                coro.close()  # type: ignore[attr-defined]
                return None
            asyncio.run_coroutine_threadsafe(coro, loop)  # type: ignore[arg-type]
            return None

        self._loop = loop
        task = loop.create_task(coro)  # type: ignore[arg-type]
        # 참조를 안 들고 있으면 GC가 실행 중인 태스크를 걷어갈 수 있다.
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task
