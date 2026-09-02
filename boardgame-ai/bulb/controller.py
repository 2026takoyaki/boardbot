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
from bulb.scenes import (
    NEUTRAL_SCENE,
    NIGHT_DIP_DARK_MS,
    NIGHT_DIP_FALL_MS,
    NIGHT_DIP_RISE_MS,
    Cue,
    Scene,
)
from core.constants import MsgType
from core.envelope import WSMessage

logger = logging.getLogger(__name__)

# Scene 적용이 실패했을 때 재시도 간격(초). 마지막 값 뒤에 한 번 더 시도하고 포기한다.
#
# 짧게 시작해 늘린다 — 순간적인 끊김이면 첫 재시도에서 붙고, 전구가 아예 없으면
# 몇 초 안에 조용해진다. 게임 진행을 막지 않도록 전부 백그라운드에서 돈다.
_SCENE_RETRY_DELAYS = (0.5, 2.0, 5.0)

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
        #
        # 색온도까지 키에 넣는다. RGB만 보면 같은 색을 RGB로 낼 때와 색온도로 낼
        # 때가 구분되지 않아, 전달 방식만 바뀐 전환이 중복 제거에 삼켜진다.
        self._last_applied: tuple[RGB, int, int | None] | None = None

        self._loop: asyncio.AbstractEventLoop | None = None
        self._cue_task: asyncio.Task[None] | None = None
        # 진행 중인 Scene 적용. 어둠을 거쳐 들어가는 Scene은 적용에 2초 넘게
        # 걸리므로(§밤 전환), 그 사이에 다음 페이즈가 오면 먼저 시작한 쪽이
        # 뒤늦게 깨어나 새 색을 옛 색으로 덮어쓴다. 새 Scene이 오면 취소한다.
        self._scene_task: asyncio.Task[None] | None = None
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
        self._cancel_scene()
        self._scene_task = self._spawn(self._apply_scene(self._scene, game))

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
        """Scene을 적용한다. 실패하면 몇 번 더 시도한다.

        재시도가 필요한 이유: Scene은 페이즈가 바뀔 때 한 번만 나간다. 그 한 번이
        실패하면 전구는 **이전 페이즈의 색을 문 채 그대로 남고**, 다음 페이즈가
        올 때까지 아무도 다시 보내지 않는다. 실제로 밤에 핸드폰 핫스팟이 잠깐
        끊긴 판에서 예언자의 파란색이 낮 토론과 투표까지 그대로 남았다.

        Cue와 달리 Scene은 "지금 방이 무슨 색이어야 하는가"라서, 늦게라도
        도착하는 편이 낫다.
        """
        for attempt, delay in enumerate(_SCENE_RETRY_DELAYS):
            if await self._apply_scene_once(scene, game):
                return
            # 취소되면(다음 페이즈가 왔다) 여기까지 오지 않는다 — CancelledError가
            # 그대로 올라가 이 루프를 끝낸다.
            logger.info(
                "light: '%s' 적용 실패 — %.1f초 뒤 재시도 (%d/%d)",
                scene.name, delay, attempt + 1, len(_SCENE_RETRY_DELAYS),
            )
            await asyncio.sleep(delay)
        if not await self._apply_scene_once(scene, game):
            logger.warning("light: '%s' 적용을 포기한다. 전구가 응답하지 않는다.", scene.name)

    async def _apply_scene_once(self, scene: Scene, game: str | None) -> bool:
        if scene.enter_via_dark and not self._is_dark():
            return await self._enter_via_dark(scene, game)
        return await self._drive(
            scene.color, scene.brightness, scene.transition_ms, game, scene.kelvin
        )

    async def _enter_via_dark(self, scene: Scene, game: str | None) -> bool:
        """어둠을 한 번 거쳐 Scene으로 들어간다.

        늑대인간 밤은 "눈을 감으세요 → 눈을 뜨세요"가 한 쌍이다. 색만 갈아끼우면
        조명은 그 중 뒤쪽만 말한다. 소등을 거치면 앞쪽까지 조명이 말해준다.

        이미 어두우면 그냥 올린다 — NIGHT_START(암전) 다음 역할처럼 방이 벌써
        캄캄한 자리에서 한 번 더 끄면 아무 일도 안 일어난 것처럼 보인다.

        소등 명령의 color/kelvin은 전구가 무시하지만(밝기 0은 소등이다) Scene의
        값을 그대로 실어 보낸다. 화면에 조명을 그리는 프론트엔드 드라이버는 이
        값으로 "무슨 색이 꺼져 있는가"를 그린다.
        """
        await self._drive(scene.color, 0, NIGHT_DIP_FALL_MS, game, scene.kelvin)
        # 페이드가 끝나고 어둠이 유지되는 시간까지 기다린다. 안 기다리면 다 꺼지기도
        # 전에 다음 색이 올라가 소등이 눈에 보이지 않는다.
        await asyncio.sleep((NIGHT_DIP_FALL_MS + NIGHT_DIP_DARK_MS) / 1000)
        # 성공 여부는 **색이 올라갔는가**로만 판단한다. 소등이 실패했어도 방이
        # 맞는 색이면 된 것이고, 소등만 성공하고 색이 안 올라가면 방이 캄캄한
        # 채로 남아 반드시 재시도해야 한다.
        return await self._drive(
            scene.color, scene.brightness, NIGHT_DIP_RISE_MS, game, scene.kelvin
        )

    def _is_dark(self) -> bool:
        """지금 전구가 꺼져 있는가. 한 번도 안 보냈으면 알 수 없으므로 False."""
        return self._last_applied is not None and self._last_applied[1] <= 0

    async def _play_cue(self, cue: Cue, game: str | None) -> None:
        """터뜨리고 반드시 Scene으로 돌아온다.

        중간에 취소되는 경우는 더 새로운 Cue나 Scene이 들어왔을 때뿐이고,
        그쪽이 곧바로 조명을 다시 몰기 때문에 어중간한 색으로 멈추지 않는다.
        세션이 끊겨 아무것도 뒤따르지 않는 경우는 reset()이 중립으로 되돌린다.
        """
        await self._drive(cue.color, cue.brightness, cue.rise_ms, game, cue.kelvin)
        # rise는 전구가 알아서 페이드하는 시간이라 우리가 기다려줘야 한다. 안
        # 기다리면 색이 다 오르기도 전에 복귀가 시작돼 total_ms가 실제 복귀
        # 시점보다 길게 잡히고, §2.4 불변식이 근거를 잃는다.
        await asyncio.sleep((cue.rise_ms + cue.hold_ms) / 1000)
        await self._drive(
            self._scene.color, self._scene.brightness, cue.fall_ms, game, self._scene.kelvin
        )

    async def _drive(
        self,
        color: RGB,
        brightness: int,
        duration_ms: int,
        game: str | None,
        kelvin: int | None = None,
    ) -> bool:
        """전구에 실제로 보낸다. 성공하면 True.

        성공/실패를 돌려주는 이유는 Scene 적용이 실패했을 때 재시도해야 하기
        때문이다 — 아래 _apply_scene 참고.
        """
        level = self._clamp(brightness, game)
        target = (color, level, kelvin)
        if target == self._last_applied:
            return True
        self._last_applied = target
        try:
            await asyncio.wait_for(
                self._driver.apply(color, level, max(0, duration_ms), kelvin),
                timeout=self._config.command_timeout_s,
            )
            return True
        except asyncio.CancelledError:
            # 취소 시점에 명령이 전구까지 갔는지 알 수 없다. "보냈다"고 캐시해두면
            # 뒤이은 중립 복귀가 중복 제거로 삼켜져 조명이 색을 문 채 멈춘다.
            self._last_applied = None
            raise
        except TimeoutError:
            # 전구가 실제로 어떤 상태인지 모르게 됐다. 캐시를 비워 다음 명령이
            # 중복 제거로 삼켜지지 않게 한다 — 삼켜지는 게 중립 복귀라면
            # 요트 인식이 그대로 깨진다.
            self._last_applied = None
            logger.warning("light: 명령 타임아웃 (rgb=%s brightness=%d)", color, level)
        except Exception:
            self._last_applied = None
            # 전구가 안 붙어 있으면 매 전환마다 같은 트레이스백이 쌓인다.
            # 원인은 한 줄이면 충분하다.
            logger.warning("light: 명령 실패 (rgb=%s brightness=%d)", color, level)
        return False

    def _clamp(self, brightness: int, game: str | None) -> int:
        """게임별 밝기 하한 적용.

        늑대인간은 하한이 0이라 완전 소등이 그대로 통과하고, 요트는 하한이 높아
        어두운 값이 들어와도 인식 가능한 밝기로 걷어올려진다. 매핑 테이블이
        실수해도 인식이 죽지 않게 하는 마지막 방어선이다.
        """
        floor = self._config.floor_for(game)
        return max(floor, min(BRIGHTNESS_MAX, brightness))

    def _resolve_cue(self, name: str, payload: dict[str, object]) -> Cue | None:
        """variant가 붙어 있으면 그 변형을 먼저 찾는다.

        FSM은 큐 이름 하나(yacht_turn_transition)에 "이게 어떤 종류의 사건인가"를
        variant로 실어 보낸다. 연출 강도는 조명 쪽 관심사이므로 FSM이 이름을
        나눌 이유가 없다.

        변형이 테이블에 없으면 기본 큐로 떨어진다. 늑대인간 담당자가 새 variant를
        만들어도 조명이 깨지지 않고, 조명에서 굳이 구분할 필요가 없는 사건은
        매핑을 비워두면 된다.
        """
        variant = payload.get("variant")
        if isinstance(variant, str) and variant:
            specific = self._cue_map.get(f"{name}_{variant}")
            if specific is not None:
                return specific
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

        Cue만이 아니라 **대기 중인 모든 명령**을 취소한다. Scene 적용도 백그라운드
        태스크라, 취소하지 않으면 중립을 세운 직후에 뒤늦게 완료되면서 다른 색으로
        덮어쓴다 — 정리했다고 믿는 순간이 가장 위험하다.

        캐시도 비운다. 취소된 명령이 전구까지 갔는지 알 수 없으므로, 중립 복귀는
        중복 제거를 건너뛰고 반드시 나가야 한다.
        """
        self._cancel_pending()
        self._game = None
        self._phase = None
        self._scene = NEUTRAL_SCENE
        self._last_applied = None
        await self._drive(
            NEUTRAL_SCENE.color,
            NEUTRAL_SCENE.brightness,
            NEUTRAL_SCENE.transition_ms,
            None,
            NEUTRAL_SCENE.kelvin,
        )

    async def aclose(self) -> None:
        """프로세스 종료 시 중립 복귀 후 연결 정리."""
        with contextlib.suppress(Exception):
            await self.reset()
        with contextlib.suppress(Exception):
            await self._driver.close()

    # ── 태스크 관리 ──────────────────────────────────────────────────────────

    def _cancel_cue(self) -> None:
        if self._cue_task is not None and not self._cue_task.done():
            self._cue_task.cancel()
        self._cue_task = None

    def _cancel_scene(self) -> None:
        if self._scene_task is not None and not self._scene_task.done():
            self._scene_task.cancel()
        self._scene_task = None

    def _cancel_pending(self) -> None:
        """Cue와 Scene 적용을 모두 취소한다. 뒤늦게 완료돼 덮어쓰는 것을 막는다."""
        self._cancel_cue()
        self._cancel_scene()
        for task in list(self._tasks):
            if not task.done():
                task.cancel()

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
