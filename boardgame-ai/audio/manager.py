"""AudioManager — 오디오 출력 단일 진입점 + ack-driven 우선순위 큐.

M1 기능:
- FSM의 tts_play/sfx_play를 가로채 합성/캐시 → audio_url 채워 broadcast.
- 캐시 hit (static/session)이면 즉시, miss면 비동기 합성.
- prewarm_session_async(): 좌석 등록 hook용 fire-and-forget.
- enqueue_llm_line(): LLM 멘트 진입점.

M2 추가:
- 우선순위 큐 (priority 오름차순, 동순위는 도착순).
- ack-driven 푸시: 한 번에 한 항목만 broadcast → frontend ack 받으면 다음.
- CRITICAL 인터럽트: 현재 재생 중 항목이 interruptible이면 tts_interrupt 발행,
  큐의 interruptible=True 항목 모두 제거, CRITICAL을 즉시 broadcast.
- 시퀀스 직렬화: 같은 sequence_id 항목은 seq_index 순서로, 앞 항목 ack 전까지 대기.

스레드 모델:
- asyncio 단일 이벤트 루프 가정.
- broadcast 콜백은 활성 세션이 attach_broadcast()로 갈아끼움.
- 동시에 1개 게임만 진행되므로 매니저는 전역 1개.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from audio.catalog import DEFAULT_VOICE, VoiceConfig
from audio.prewarm import make_session_id, prewarm_session, wipe_session
from audio.tts_engine import CacheLayer, TTSEngine
from core.audio import AudioPriority, SFXRequest, TTSRequest
from core.constants import MsgType
from core.envelope import WSMessage
from core.persona import Delivery, Persona

logger = logging.getLogger(__name__)


def _fallback_persona() -> Persona:
    """페르소나가 주입되지 않았을 때(테스트 등) 쓰는 최소 인격.

    없으면 목소리 조회가 죽어 발화가 통째로 사라진다. 조용히 기본값으로
    돌아가는 편이 낫다 — 진행이 멈추는 것보다 목소리가 밋밋한 게 낫다.
    """
    return Persona(
        id="fallback",
        display_name="진행자",
        voice_name=DEFAULT_VOICE.name,
        language_code=DEFAULT_VOICE.language_code,
        base=Delivery(
            speaking_rate=DEFAULT_VOICE.speaking_rate, pitch=DEFAULT_VOICE.pitch
        ),
    )

BroadcastFn = Callable[[WSMessage], Awaitable[None]]

# 이름 슬롯. 세션 캐시를 데울 때 이 자리만 채운다. 규칙은 agents/tools/lines.py의
# fill()과 같아야 하는데, audio가 그쪽을 import하면 계층이 뒤집혀 여기 둔다.
_PLAYER_SLOT = "{player}"


def _fill_player(template: str, name: str) -> str:
    return template.replace(_PLAYER_SLOT, name)


def _new_playback_id() -> str:
    return f"pb_{uuid.uuid4().hex[:10]}"


@dataclass
class _QueueItem:
    """큐에 들어가는 단일 재생 항목. 합성은 dequeue 직전에 일어남."""

    priority: int
    seq_arrival: int  # 도착 순서 (priority 동률 tiebreaker)
    msg: WSMessage  # tts_play 또는 sfx_play WSMessage (audio_url 미충전 상태일 수 있음)
    playback_id: str
    interruptible: bool
    sequence_id: str | None = None
    seq_index: int = 0
    state_version: int = 0  # FSM 진행 단계. 사용자가 다음 단계 가면 옛 항목은 stale.


class AudioManager:
    """오디오 출력 단일 진입점.

    사용:
        mgr = AudioManager(engine)
        mgr.attach_broadcast(session.send)
        # FSM이 만든 tts_play WSMessage를 세션이 받으면:
        if msg.msg_type in AUDIO_MSG_TYPES:
            await mgr.handle_outbound(msg)
    """

    def __init__(self, engine: TTSEngine, persona: Persona | None = None) -> None:
        self._engine = engine
        self._broadcast: BroadcastFn | None = None
        self._active_session_id: str | None = None
        # 목소리의 소유자. 누가 말하든 이 한 사람의 목소리로 나가고, 에이전트는
        # 그 안에서 말투만 갈린다. audio는 페르소나를 고르지 않고 받아만 쓴다.
        self._persona: Persona = persona or _fallback_persona()
        # 미리 만들어 둘 수 있는 문장들. 문장의 소유자는 에이전트 계층이라
        # audio가 직접 읽지 않고 주입받는다(set_line_catalog).
        self._static_texts: frozenset[str] = frozenset()
        # 이름 슬롯이 있는 템플릿. 좌석이 정해지면 이름을 채워 아래를 만든다.
        self._session_templates: tuple[str, ...] = ()
        # 이름까지 채워진 실제 발화 문장. 계층 판정은 이쪽을 본다 —
        # 발화되는 것은 템플릿이 아니라 완성된 문장이다.
        self._session_texts: frozenset[str] = frozenset()
        # 기본이 아닌 말투로 나가는 문장들. {말투: [문장]}
        # 캐시 키에 말투가 들어가므로, 기본 말투로만 데워두면 심판 말투 발화는
        # 매번 캐시 미스가 된다. 가장 급해야 할 제지가 가장 느려지는 경로다.
        self._delivery_static: dict[str, list[str]] = {}
        self._delivery_templates: dict[str, list[str]] = {}

        # 큐: priority 오름차순(1=CRITICAL이 최우선), 동순위는 seq_arrival 오름차순.
        self._queue: list[_QueueItem] = []
        self._arrival_counter = itertools.count()

        # 현재 재생 중인 항목 (frontend가 ack 보내기 전까지 유지).
        self._current: _QueueItem | None = None
        # 다음 항목 푸시를 직렬화하는 lock (race 방지).
        self._push_lock = asyncio.Lock()

    # ── 캐시 계층 ─────────────────────────────────────────────────────────────

    def set_line_catalog(
        self,
        static_texts: Iterable[str],
        session_templates: Iterable[str] = (),
        delivery_static: Mapping[str, Iterable[str]] | None = None,
        delivery_templates: Mapping[str, Iterable[str]] | None = None,
    ) -> None:
        """미리 만들어 둘 수 있는 문장 목록을 갱신한다.

        페르소나가 바뀌면 문장이 통째로 달라지므로 같이 갱신해야 한다.
        안 하면 prewarm은 옛 문장을 만들어 두고, 실제 발화는 전부 캐시 miss가
        되어 매 페이즈 첫 마디마다 합성 지연이 붙는다.
        """
        self._static_texts = frozenset(static_texts)
        self._session_templates = tuple(session_templates)
        # 말투별 목록은 위 두 목록의 부분집합이다. 계층 판정은 위 목록이
        # 그대로 하고, 이건 "어느 말투로 한 번 더 데울지"만 정한다.
        self._delivery_static = {
            role: list(texts) for role, texts in (delivery_static or {}).items()
        }
        self._delivery_templates = {
            role: list(texts) for role, texts in (delivery_templates or {}).items()
        }
        # 페르소나가 바뀌면 이름을 채워둔 문장도 옛 말투다. 좌석이 다시
        # 등록될 때 새로 만든다.
        self._session_texts = frozenset()

    async def add_static_texts(
        self, texts: Iterable[str], prewarm: bool = True
    ) -> dict[str, int]:
        """뒤늦게 정해진 문장을 static 목록에 더하고 합성해 둔다.

        페르소나를 고르는 시점에는 아직 없고 조금 뒤에 만들어지는 문장이 있다
        (LLM이 만드는 템포 변형). 그것을 기다렸다 부팅을 마치면 서버가 10초
        늦게 뜨므로, 먼저 뜨고 나중에 더한다.

        목록에 넣지 않으면 계층 판정이 dynamic으로 떨어져 그 문장이 처음
        나올 때마다 합성 지연이 붙는다 — 미리 만들어 둔 의미가 없어진다.
        """
        items = [t for t in texts if t.strip()]
        if not items:
            return {}
        self._static_texts = self._static_texts | frozenset(items)
        if not prewarm:
            return {}
        from audio.prewarm import prewarm_static

        stats = await prewarm_static(self._engine, self._persona, items)
        logger.info("add_static_texts(%d줄): prewarm %s", len(items), stats)
        return stats

    # ── 페르소나 ──────────────────────────────────────────────────────────────

    @property
    def persona(self) -> Persona:
        return self._persona

    async def set_persona(self, persona: Persona, prewarm: bool = True) -> dict[str, int]:
        """진행자를 바꾼다. 캐시 키가 목소리 파라미터로 만들어지므로, 바꾸면
        기존 static 캐시가 전부 miss가 된다. 그대로 두면 게임 내내 첫 발화마다
        합성 지연이 붙으므로 새 페르소나로 다시 데워둔다.

        prewarm=False는 테스트용 — 합성 없이 목소리만 갈아끼운다.
        """
        self._persona = persona
        if not prewarm:
            return {}
        from audio.prewarm import prewarm_static

        stats = await prewarm_static(self._engine, persona, self._static_texts)
        # 기본 말투로 데운 파일은 심판 말투 발화에 쓰이지 못한다 — 캐시 키에
        # 말투가 들어가 같은 문장이라도 키가 다르다. 그 말투로 한 번 더 데운다.
        for role, texts in self._delivery_static.items():
            extra = await prewarm_static(self._engine, persona, texts, role=role)
            for key, value in extra.items():
                stats[key] = stats.get(key, 0) + value
        logger.info("set_persona(%s): prewarm %s", persona.id, stats)
        return stats

    # ── 세션 라이프사이클 ──────────────────────────────────────────────────────

    def attach_broadcast(
        self, broadcast: BroadcastFn, session_id: str | None = None
    ) -> None:
        """활성 세션의 broadcast 함수 연결. 이전 세션의 stale 상태도 초기화."""
        self._broadcast = broadcast
        self._active_session_id = session_id
        # 이전 세션의 _current/_queue가 남아 있으면 새 세션 TTS가 막히므로 초기화.
        self._current = None
        self._queue.clear()
        logger.info("AudioManager broadcast attached (session_id=%s)", session_id)

    def detach_broadcast(self) -> None:
        """세션 disconnect 시 호출. 큐·현재 재생 모두 정리해 다음 세션이 깨끗하게 시작.

        끊긴 세션이 frontend ack을 보낼 수 없으므로 _current를 그대로 두면
        새 세션에서도 큐 진행이 막힘. 강제 비움.
        """
        self._broadcast = None
        self._active_session_id = None
        self._current = None
        self._queue.clear()
        logger.info("AudioManager broadcast detached + queue cleared")

    def detach_broadcast_if(self, broadcast: BroadcastFn) -> None:
        """broadcast가 현재 등록된 것과 동일한 경우에만 detach.

        race condition 방지: 구 세션 disconnect가 신 세션 attach 이후에 처리될 때
        신 세션의 broadcast를 잘못 지우지 않도록 한다.
        """
        if self._broadcast is broadcast:
            self.detach_broadcast()
        else:
            logger.debug("detach_broadcast_if: 건너뜀 (이미 다른 세션이 attach됨)")

    def get_session_id(self) -> str | None:
        return self._active_session_id

    # ── prewarm 헬퍼 ──────────────────────────────────────────────────────────

    def prewarm_session_async(self, player_names: list[str]) -> str:
        """좌석이 정해졌으니 이름을 채운 문장들을 미리 합성한다.

        어떤 문장에 이름이 들어가는지는 세션 문장 목록(set_line_catalog)이
        알고 있다. 여기서 이름만 채워 넣는다.
        """
        session_id = make_session_id(player_names)
        self._active_session_id = session_id
        texts = [
            _fill_player(template, name)
            for template in self._session_templates
            for name in player_names
        ]
        # 계층 판정이 볼 목록. 미리 합성한 것과 같은 문자열이어야 hit된다.
        self._session_texts = frozenset(texts)

        # 심판 말투로 나가는 것들("지금은 성민님 차례입니다")은 그 말투로도
        # 데워야 한다. 이름을 채우는 방식은 기본 말투와 같다.
        by_role = {
            role: [
                _fill_player(template, name)
                for template in templates
                for name in player_names
            ]
            for role, templates in self._delivery_templates.items()
        }

        async def _run() -> None:
            try:
                await prewarm_session(
                    self._engine, session_id, texts, self._persona
                )
                for role, role_texts in by_role.items():
                    await prewarm_session(
                        self._engine, session_id, role_texts, self._persona, role=role
                    )
            except Exception:
                logger.exception("prewarm_session_async failed (%s)", session_id)

        asyncio.create_task(_run())
        logger.info(
            "prewarm_session_async scheduled (session_id=%s, players=%s)",
            session_id, player_names,
        )
        return session_id

    def wipe_session_cache(self, session_id: str) -> None:
        wipe_session(session_id)
        if self._active_session_id == session_id:
            self._active_session_id = None

    # ── outbound: FSM → AudioManager → frontend ───────────────────────────────

    async def handle_outbound(self, msg: WSMessage) -> None:
        """FSM이 emit한 audio 메시지 라우팅."""
        t = msg.msg_type
        if t == MsgType.TTS_PLAY.value:
            await self._enqueue_tts_play_msg(msg)
        elif t == MsgType.SFX_PLAY.value:
            await self._enqueue_sfx_msg(msg)
        elif t == MsgType.TTS_INTERRUPT.value:
            # FSM이 직접 인터럽트 요청 (드문 경우)
            pbid = msg.payload.get("playback_id")
            await self._interrupt(pbid)
        elif t in (MsgType.BGM_PLAY.value, MsgType.BGM_DUCK.value):
            # BGM은 큐 외부. 항상 즉시 pass-through.
            await self._send(msg)
        else:
            logger.warning("handle_outbound: unexpected msg_type=%s", t)

    async def _enqueue_tts_play_msg(self, msg: WSMessage) -> None:
        request = TTSRequest.from_dict(msg.payload)
        if not request.playback_id:
            request.playback_id = _new_playback_id()
        # 메시지 갱신
        msg.payload = request.to_dict()
        # Benchmark hook: 큐 입장 시각 (채널별 응답 시간 분해용).
        try:
            import time as _t

            from benchmarks.common.trace_setup import bench_log
            bench_log().info(
                "audio_enqueue tts_play %s %.6f", request.playback_id, _t.time(),
            )
        except Exception:
            pass
        item = _QueueItem(
            priority=int(request.priority),
            seq_arrival=next(self._arrival_counter),
            msg=msg,
            playback_id=request.playback_id,
            interruptible=request.interruptible,
            sequence_id=request.sequence_id,
            seq_index=request.seq_index,
            state_version=request.state_version,
        )
        await self._enqueue(item)

    async def _enqueue_sfx_msg(self, msg: WSMessage) -> None:
        payload = dict(msg.payload)
        if not payload.get("playback_id"):
            payload["playback_id"] = _new_playback_id()
            msg.payload = payload
        # Benchmark hook: 큐 입장 시각.
        try:
            import time as _t

            from benchmarks.common.trace_setup import bench_log
            bench_log().info(
                "audio_enqueue sfx_play %s %.6f", payload["playback_id"], _t.time(),
            )
        except Exception:
            pass
        item = _QueueItem(
            priority=int(payload.get("priority", AudioPriority.NORMAL)),
            seq_arrival=next(self._arrival_counter),
            msg=msg,
            playback_id=payload["playback_id"],
            interruptible=bool(payload.get("interruptible", True)),
            sequence_id=payload.get("sequence_id"),
            seq_index=int(payload.get("seq_index", 0)),
        )
        await self._enqueue(item)

    async def _enqueue(self, item: _QueueItem) -> None:
        """큐에 항목 삽입. CRITICAL이면 현재 재생 인터럽트.

        새 state_version의 항목이 들어오면 큐의 옛 interruptible 항목은 자동 폐기.
        사용자가 게임 흐름을 빠르게 진행시킬 때 옛 안내가 쌓이지 않게 함.
        """
        self._queue.append(item)
        self._queue.sort(key=lambda q: (q.priority, q.seq_arrival))

        # 새 진행 단계(state_version) 도착 → 큐의 stale interruptible 항목 폐기 +
        # 재생 중 항목이 stale이고 interruptible이면 fade-out 인터럽트.
        # 정책: 일반 진행 멘트(NORMAL/HIGH)에만 적용. CRITICAL은 항상 보존.
        if item.state_version > 0 and item.priority != AudioPriority.CRITICAL:
            self._drop_stale_versions(item.state_version)
            if (
                self._current is not None
                and self._current.interruptible
                and self._current.priority != AudioPriority.CRITICAL
                and self._current.state_version < item.state_version
            ):
                logger.info(
                    "interrupting stale current playback (v=%d < %d)",
                    self._current.state_version, item.state_version,
                )
                await self._interrupt_current("stale_state_version")

        if (
            item.priority == AudioPriority.CRITICAL
            and self._current is not None
            and self._current.interruptible
        ):
            # 현재 재생을 fade-out 인터럽트 + interruptible 큐 항목 제거.
            await self._interrupt_current("preempted_by_critical")
            self._drop_interruptible_from_queue()

        await self._maybe_push_next()

    def _drop_stale_versions(self, current_version: int) -> None:
        """현재보다 오래된 state_version의 interruptible 항목을 큐에서 제거."""
        before = len(self._queue)
        self._queue = [
            q for q in self._queue
            if (q.state_version >= current_version)
            or (not q.interruptible)
            or (q.priority == AudioPriority.CRITICAL)
        ]
        dropped = before - len(self._queue)
        if dropped:
            logger.info(
                "queue: dropped %d stale items (state_version < %d)",
                dropped, current_version,
            )

    def _drop_interruptible_from_queue(self) -> None:
        """interruptible=True 항목만 큐에서 제거. CRITICAL/non-interruptible은 보존."""
        before = len(self._queue)
        # 새로 들어온 CRITICAL 자체는 제거하면 안 됨 → priority가 CRITICAL인 항목은 보존.
        self._queue = [
            q for q in self._queue
            if (not q.interruptible) or q.priority == AudioPriority.CRITICAL
        ]
        dropped = before - len(self._queue)
        if dropped:
            logger.info("queue: dropped %d interruptible items on CRITICAL preempt", dropped)

    async def _interrupt_current(self, reason: str) -> None:
        """현재 재생 항목에 인터럽트 신호 발행. frontend가 fade-out 후 ack 보냄."""
        if self._current is None:
            return
        msg = WSMessage.make_tts_interrupt(playback_id=self._current.playback_id)
        logger.info(
            "interrupt_current: playback_id=%s reason=%s",
            self._current.playback_id, reason,
        )
        await self._send(msg)
        # _current는 frontend ack를 기다리지 않고 즉시 비움.
        # ack가 늦게 와도 멱등하게 처리됨.
        self._current = None

    async def _interrupt(self, playback_id: str | None) -> None:
        """특정 playback_id 또는 현재 재생을 인터럽트."""
        if playback_id and self._current and self._current.playback_id != playback_id:
            # 큐에서 제거
            self._queue = [q for q in self._queue if q.playback_id != playback_id]
            return
        await self._interrupt_current("explicit_interrupt")
        await self._maybe_push_next()

    async def interrupt_interruptible(self, reason: str = "explicit_interrupt_all") -> None:
        """현재 interruptible 재생과 큐의 interruptible 항목을 모두 정리."""
        self._drop_interruptible_from_queue()
        if (
            self._current is not None
            and self._current.interruptible
            and self._current.priority != AudioPriority.CRITICAL
        ):
            await self._interrupt_current(reason)
        await self._maybe_push_next()

    async def _maybe_push_next(self) -> None:
        """현재 재생 없으면 큐의 다음 항목을 합성·broadcast."""
        async with self._push_lock:
            if self._current is not None or not self._queue:
                return

            # sequence_id 직렬화: 같은 sequence의 더 작은 seq_index가 있으면 그것부터.
            # 현재는 정렬이 priority 기반이므로 sequence는 자연스럽게 보장되지 않음 →
            # 다음 항목이 sequence에 속하면 같은 sequence 내 최소 seq_index 선택.
            next_idx = self._select_next_index()
            if next_idx is None:
                return
            item = self._queue.pop(next_idx)
            self._current = item

        try:
            import time as _t

            from benchmarks.common.trace_setup import bench_log
            bench_log().info(
                "audio_dequeue %s %s %.6f",
                item.msg.msg_type, item.playback_id, _t.time(),
            )
        except Exception:
            pass
        await self._broadcast_item(item)

    def _select_next_index(self) -> int | None:
        """다음 dequeue할 인덱스. 일반적으로 0이지만 sequence 직렬화 고려."""
        if not self._queue:
            return None
        # 큐는 (priority, arrival)로 정렬됨. 첫 항목이 sequence에 속한다면
        # 같은 sequence 내 더 작은 seq_index가 큐에 있는지 확인.
        head = self._queue[0]
        if head.sequence_id is None:
            return 0
        # 같은 sequence_id 중 최소 seq_index를 가진 항목을 우선.
        min_idx_in_seq = None
        min_seq_value = None
        for i, q in enumerate(self._queue):
            if q.sequence_id != head.sequence_id:
                continue
            if min_seq_value is None or q.seq_index < min_seq_value:
                min_seq_value = q.seq_index
                min_idx_in_seq = i
        return min_idx_in_seq if min_idx_in_seq is not None else 0

    async def _broadcast_item(self, item: _QueueItem) -> None:
        """합성/캐시 → audio_url 채워 broadcast."""
        msg = item.msg
        if msg.msg_type == MsgType.TTS_PLAY.value:
            request = TTSRequest.from_dict(msg.payload)
            voice = self._voice_for(request)
            layer, layer_session_id = self._layer_for(request.text)
            path = self._engine.cache_hit(request.text, voice, layer, session_id=layer_session_id)
            if path is None:
                path = await self._engine.synthesize(
                    request.text, voice, layer, session_id=layer_session_id
                )
            if path is not None:
                request.audio_url = self._audio_url_for(path, layer, layer_session_id)
            else:
                logger.warning(
                    "tts: synthesis failed, sending text-only (playback_id=%s)",
                    request.playback_id,
                )
            out = WSMessage.make_tts_play(request, state_version=msg.state_version)
            # Benchmark hook: backend → frontend 송신 시각.
            try:
                import time as _t

                from benchmarks.common.trace_setup import bench_log
                bench_log().info(
                    "audio_broadcast tts_play %s %.6f",
                    request.playback_id, _t.time(),
                )
            except Exception:
                pass
            await self._send(out)
        else:
            try:
                import time as _t

                from benchmarks.common.trace_setup import bench_log
                pbid = msg.payload.get("playback_id", "-") if isinstance(msg.payload, dict) else "-"
                bench_log().info(
                    "audio_broadcast %s %s %.6f", msg.msg_type, pbid, _t.time(),
                )
            except Exception:
                pass
            await self._send(msg)

    # ── inbound: frontend → AudioManager ──────────────────────────────────────

    async def handle_ack(self, playback_id: str, status: str) -> None:
        """frontend가 재생 완료/중단 통보. 큐 진행."""
        logger.debug("audio_ack: playback_id=%s status=%s", playback_id, status)
        # 멱등성: 이미 _current가 비워졌으면(인터럽트 race) 그대로 진행.
        if self._current is not None and self._current.playback_id == playback_id:
            self._current = None
        await self._maybe_push_next()

    # ── 외부 호출용 enqueue API ───────────────────────────────────────────────

    async def enqueue_tts(
        self,
        text: str,
        agent: str = "narrator",
        priority: AudioPriority = AudioPriority.NORMAL,
        sequence_id: str | None = None,
        seq_index: int = 0,
        interruptible: bool = True,
        state_version: int = 0,
    ) -> str:
        """FSM 외부에서 직접 TTS를 큐에 넣을 때 (테스트/LLM 진입점/SFX 시퀀스)."""
        req = TTSRequest(
            text=text,
            priority=priority,
            agent=agent,
            interruptible=interruptible,
            playback_id=_new_playback_id(),
            sequence_id=sequence_id,
            seq_index=seq_index,
            state_version=state_version,
        )
        msg = WSMessage.make_tts_play(req, state_version=state_version)
        await self._enqueue_tts_play_msg(msg)
        assert req.playback_id is not None
        return req.playback_id

    async def enqueue_sfx(
        self,
        name: str,
        priority: AudioPriority = AudioPriority.NORMAL,
        sequence_id: str | None = None,
        seq_index: int = 0,
        interruptible: bool = True,
    ) -> str:
        from audio.catalog import SFX_REGISTRY

        audio_url = SFX_REGISTRY.get(name)
        if audio_url is None:
            logger.warning("enqueue_sfx: unknown SFX name=%r", name)
            return ""
        req = SFXRequest(
            name=name,
            audio_url=audio_url,
            priority=priority,
            interruptible=interruptible,
            playback_id=_new_playback_id(),
            sequence_id=sequence_id,
            seq_index=seq_index,
        )
        msg = WSMessage.make_sfx_play(req)
        await self._enqueue_sfx_msg(msg)
        assert req.playback_id is not None
        return req.playback_id

    async def play_bgm(
        self,
        name: str,
        loop: bool = True,
        gain_db: float = -6.0,
        fade_ms: int = 500,
    ) -> None:
        """BGM 트랙 시작 (또는 교체). 큐 외부, 항상 즉시 broadcast.

        TTS와 동시 재생되며 TTS 시작 시 자동으로 ducking됨.
        """
        from audio.catalog import BGM_REGISTRY

        audio_url = BGM_REGISTRY.get(name)
        if audio_url is None:
            logger.warning("play_bgm: unknown BGM name=%r", name)
            return
        msg = WSMessage.make_bgm_play(
            name=name, audio_url=audio_url, loop=loop, gain_db=gain_db, fade_ms=fade_ms,
        )
        await self._send(msg)

    async def stop_bgm(self, fade_ms: int = 500) -> None:
        """BGM 정지. 빈 audio_url로 bgm_play를 보내 frontend가 멈춤 처리."""
        msg = WSMessage.make_bgm_play(
            name="", audio_url="", loop=False, gain_db=-60.0, fade_ms=fade_ms,
        )
        await self._send(msg)

    async def pause_bgm(self, fade_ms: int = 500) -> None:
        """BGM 일시정지. frontend는 현재 재생 위치를 보존한다."""
        msg = WSMessage.make_bgm_play(
            name="", audio_url="", loop=True, gain_db=-60.0, fade_ms=fade_ms,
        )
        msg.payload["preserve_position"] = True
        await self._send(msg)

    async def enqueue_llm_line(
        self,
        agent: str,
        text: str,
        priority: AudioPriority = AudioPriority.NORMAL,
        sequence_id: str | None = None,
        seq_index: int = 0,
    ) -> str:
        """LLM 멀티에이전트 멘트 진입점."""
        return await self.enqueue_tts(
            text=text,
            agent=agent,
            priority=priority,
            sequence_id=sequence_id,
            seq_index=seq_index,
        )

    # ── 내부 헬퍼 ─────────────────────────────────────────────────────────────

    def _voice_for(self, request: TTSRequest) -> VoiceConfig:
        """누가 말하든 페르소나의 목소리. 말투만 상황에 따라 갈린다.

        agent에 DELIVERY_EXCITED("excited")를 넣으면 흥분 말투가 된다 —
        어떤 문장이 흥분인지는 말하는 쪽이 안다.
        """
        return self._persona.voice_for(request.agent)

    def _layer_for(self, text: str) -> tuple[CacheLayer, str | None]:
        """이 문장을 어느 캐시에 넣을지.

        판정 기준은 "미리 만들어 둘 수 있는가"다.
          static  — 슬롯이 없어 그대로 나가는 문장. 부팅 때 만들어 둔다.
          session — 이름만 채우면 되는 문장. 좌석이 정해지면 만들어 둔다.
          dynamic — 주사위 값·점수처럼 매번 달라 미리 만들 수 없는 것.

        목록은 페르소나가 바뀔 때마다 갱신된다(set_line_catalog). 고정 목록을
        따로 두면 페르소나가 문장을 바꿨을 때 전부 어긋나 캐시가 통째로 논다.
        """
        if text in self._static_texts:
            return "static", None
        if self._active_session_id is not None and text in self._session_texts:
            return "session", self._active_session_id
        return "dynamic", None

    @staticmethod
    def _audio_url_for(path: Any, layer: CacheLayer, session_id: str | None) -> str:
        filename = path.name if hasattr(path, "name") else str(path).rsplit("/", 1)[-1]
        if layer == "session" and session_id:
            return f"/cache/tts/session/{session_id}/{filename}"
        return f"/cache/tts/{layer}/{filename}"

    async def _send(self, msg: WSMessage) -> None:
        if self._broadcast is None:
            logger.debug(
                "AudioManager._send: no broadcast attached, dropping msg_type=%s",
                msg.msg_type,
            )
            return
        try:
            await self._broadcast(msg)
        except Exception:
            logger.exception("AudioManager broadcast failed (msg_type=%s)", msg.msg_type)
