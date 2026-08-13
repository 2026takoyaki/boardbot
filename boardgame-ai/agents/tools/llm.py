"""LLM 공용 클라이언트.

네 에이전트가 모두 쓴다. 각자 클라이언트를 만들면 모델명이 네 군데에 박히고,
커넥션도 재사용되지 않으며, 무엇보다 **실패가 조용히 삼켜져 왜 안 되는지
알 수 없게 된다** — 실제로 그랬다. strategy_agent가 `max_tokens`를 보내
매번 400을 받고 있었는데, except가 삼켜서 "LLM이 그냥 안 붙은 것"처럼 보였다.

호출 비용:
    응답 ~1초 + TTS 합성 ~1~2초 = 발화까지 2~3초.
    그래서 "누가 기다리는가"에 따라 부르는 방식이 다르다.
      Strategy  지연 허용   → 직접 호출
      Progress  상황 멘트만 → 백그라운드
      Rules     즉답 필요   → 캐시 즉답 뒤에 이어 붙임
      Tempo     재료 없음   → 시작 시 미리 생성해 풀에 담아둠

환경:
    OPENAI_API_KEY   .env
    LLM_MODEL        생략 시 아래 기본값
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# 실측으로 고른 기본값. 바꿀 때는 tools/llm_check.py로 실제 응답을 확인할 것 —
# 모델마다 받는 파라미터가 다르다.
DEFAULT_MODEL = "gpt-5.4-mini"

# 게임이 기다리는 시간이다. 넘으면 그 멘트는 포기하고 원문/캐시로 간다.
DEFAULT_TIMEOUT = 4.0

# TTS가 그대로 읽어버리는 것들. 프롬프트로 아무리 당부해도 가끔 섞여 나온다.
_STRIP = re.compile(r"[*_#`\[\]<>|]|[\U0001F300-\U0001FAFF☀-➿]")


@dataclass(frozen=True)
class LLMResult:
    """호출 결과. 실패해도 예외를 던지지 않는다 — 멘트 하나 때문에 게임이
    멈추면 안 되므로, 부르는 쪽이 ok를 보고 폴백을 고르게 한다."""

    text: str | None
    ok: bool
    latency_ms: float
    error: str | None = None
    tokens: int = 0


@dataclass
class _Stats:
    calls: int = 0
    ok: int = 0
    failed: int = 0
    timeouts: int = 0
    cancelled: int = 0
    total_tokens: int = 0
    total_ms: float = 0.0
    last_error: str | None = None
    last_call_at: float | None = None
    by_tag: dict[str, int] = field(default_factory=dict)


def sanitize_for_tts(text: str) -> str:
    """LLM 출력을 발화 가능한 형태로 다듬는다.

    출력이 곧 TTS 입력이라 마크다운이 섞이면 "별표 별표 풀하우스"로 읽힌다.
    프롬프트만 믿지 않고 여기서 한 번 더 걷어낸다.
    """
    cleaned = _STRIP.sub("", text)
    # 줄바꿈은 문장 사이 침묵으로 읽히기도 하고 무시되기도 한다. 공백으로 통일.
    cleaned = " ".join(cleaned.split())
    return cleaned.strip().strip('"').strip()


def _unfence(text: str) -> str:
    """JSON 응답에서 코드펜스만 벗긴다.

    response_format을 줘도 ```json으로 감싸 오는 경우가 있다. 내용은 건드리지
    않는다 — 여기서 문자를 지우면 파싱이 깨진다.
    """
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped[3:].removesuffix("```")
    # ```json 처럼 언어 표시가 붙어 있으면 첫 줄을 버린다.
    first, _, rest = body.partition("\n")
    return (rest if first.strip().isalpha() else body).strip()


def persona_style() -> str:
    """현재 페르소나의 말투 지시. 모든 프롬프트 앞에 붙인다.

    고정 멘트는 미리 변환해두지만 LLM이 즉석에서 만든 문장은 여기서 말투를
    입혀야 한다. 안 그러면 진행자가 그 한 줄만 갑자기 표준어로 말한다.

    지연 import인 이유: agents.personas가 이 모듈을 쓰게 되면 순환이 된다.
    """
    from agents.personas import get_persona
    from agents.tools import lines

    persona = get_persona(lines.active_persona_id())
    return f"{persona.style_prompt}\n\n" if persona.style_prompt else ""


class LLMClient:
    """OpenAI 호출 한 곳. 모델명·타임아웃·재시도·로깅을 여기서만 정한다."""

    def __init__(self, model: str | None = None, timeout: float = DEFAULT_TIMEOUT) -> None:
        # 환경변수는 호출 시점에 읽는다. import 시점에 읽으면 backend/server.py의
        # load_dotenv보다 먼저 돌아 빈 값을 잡는다.
        self._model = model or os.environ.get("LLM_MODEL") or DEFAULT_MODEL
        self._timeout = timeout
        self._client: Any = None
        self._stats = _Stats()

    @property
    def model(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return bool(os.environ.get("OPENAI_API_KEY")) and self._ensure_client() is not None

    def unavailable_reason(self) -> str:
        if not os.environ.get("OPENAI_API_KEY"):
            return "OPENAI_API_KEY 미설정"
        if self._ensure_client() is None:
            return "openai 클라이언트를 만들 수 없음"
        return ""

    def _ensure_client(self) -> Any:
        if self._client is not None:
            return self._client
        # AsyncOpenAI()는 키가 없으면 생성 자체가 예외를 던진다. 여기서 막지
        # 않으면 "LLM 되나?" 물어보는 것만으로 서버가 터진다.
        if not os.environ.get("OPENAI_API_KEY"):
            return None
        try:
            from openai import AsyncOpenAI

            # 클라이언트는 한 번만 만든다. 호출마다 새로 만들면 커넥션 풀이 논다.
            self._client = AsyncOpenAI()
        except Exception as exc:  # noqa: BLE001 — 없으면 없는 대로 돌아야 한다
            logger.warning("[LLM] 클라이언트 생성 실패: %s", exc)
            return None
        return self._client

    async def complete(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 120,
        timeout: float | None = None,
        tag: str = "",
    ) -> LLMResult:
        """한 문장~두 문장 생성. 실패해도 예외 대신 ok=False를 돌려준다."""
        return await self._call(
            system, user, max_tokens=max_tokens, timeout=timeout, tag=tag, as_json=False
        )

    async def complete_json(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 800,
        timeout: float | None = None,
        tag: str = "",
    ) -> LLMResult:
        """JSON 객체 생성. 여러 개를 한 번에 받을 때(사전생성 풀 등) 쓴다."""
        return await self._call(
            system, user, max_tokens=max_tokens, timeout=timeout, tag=tag, as_json=True
        )

    async def _call(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int,
        timeout: float | None,
        tag: str,
        as_json: bool,
    ) -> LLMResult:
        started = time.time()
        self._stats.calls += 1
        self._stats.last_call_at = started
        if tag:
            self._stats.by_tag[tag] = self._stats.by_tag.get(tag, 0) + 1

        client = self._ensure_client()
        if client is None or not os.environ.get("OPENAI_API_KEY"):
            return self._fail(started, self.unavailable_reason())

        kwargs: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            # max_tokens가 아니라 max_completion_tokens다. 최신 모델은 전자를
            # 400으로 거부한다 — 이걸 몰라 호출이 전부 실패하고 있었다.
            "max_completion_tokens": max_tokens,
        }
        if as_json:
            kwargs["response_format"] = {"type": "json_object"}

        try:
            response = await asyncio.wait_for(
                client.chat.completions.create(**kwargs),
                timeout=timeout if timeout is not None else self._timeout,
            )
        except TimeoutError:
            self._stats.timeouts += 1
            return self._fail(started, "타임아웃")
        except asyncio.CancelledError:
            # 상황이 지나가 부르는 쪽이 취소한 경우. 실패가 아니므로 failed로
            # 세지 않는다. 그렇다고 안 세면 calls만 늘어 통계가 어긋난다.
            self._stats.cancelled += 1
            raise
        except Exception as exc:  # noqa: BLE001 — 멘트 하나로 게임이 멈추면 안 된다
            return self._fail(started, f"{type(exc).__name__}: {exc}")

        # content가 None으로 오는 경우가 있다(토큰 예산을 다 쓴 경우 등).
        # .strip()을 바로 부르면 AttributeError로 죽는다.
        raw = response.choices[0].message.content if response.choices else None
        # JSON 응답에는 sanitize를 걸지 않는다. 마크다운을 걷어내는 정규식이
        # 대괄호를 지워 배열이 깨진다 — 실제로 tempo 변형이 전부 이것 때문에
        # 파싱 실패로 버려졌다. JSON 안의 문장은 부르는 쪽이 따로 정화한다.
        text = (_unfence(raw) if as_json else sanitize_for_tts(raw)) if raw else ""
        tokens = getattr(getattr(response, "usage", None), "completion_tokens", 0) or 0

        elapsed_ms = (time.time() - started) * 1000
        self._stats.total_tokens += tokens

        # total_ms는 여기서 더하지 않는다. 빈 응답이면 _fail이 다시 더해
        # 같은 호출이 두 번 계산되고 avg_ms가 부풀려진다.
        if not text:
            return self._fail(started, "빈 응답", elapsed_ms=elapsed_ms)

        self._stats.total_ms += elapsed_ms
        self._stats.ok += 1
        logger.info("[LLM] %s ok %.0fms %dtok", tag or "-", elapsed_ms, tokens)
        return LLMResult(text=text, ok=True, latency_ms=elapsed_ms, tokens=tokens)

    def _fail(self, started: float, error: str, elapsed_ms: float | None = None) -> LLMResult:
        ms = elapsed_ms if elapsed_ms is not None else (time.time() - started) * 1000
        self._stats.failed += 1
        self._stats.last_error = error
        self._stats.total_ms += ms
        # 조용히 넘어가면 왜 LLM이 안 붙는지 알 수 없다. 반드시 남긴다.
        logger.warning("[LLM] 실패 %.0fms — %s", ms, error)
        return LLMResult(text=None, ok=False, latency_ms=ms, error=error)

    def stats(self) -> dict[str, Any]:
        """디버그 엔드포인트가 읽는다. "지금 LLM이 되는가"를 한눈에."""
        s = self._stats
        return {
            "model": self._model,
            "available": self.is_available(),
            "unavailable_reason": self.unavailable_reason(),
            "calls": s.calls,
            "ok": s.ok,
            "failed": s.failed,
            "timeouts": s.timeouts,
            # 상황이 지나가 취소된 호출. 이게 크면 훈수 요청이 너무 잦다는 뜻이다.
            "cancelled": s.cancelled,
            "avg_ms": round(s.total_ms / s.calls, 1) if s.calls else 0.0,
            "total_tokens": s.total_tokens,
            "last_error": s.last_error,
            "by_tag": dict(s.by_tag),
        }


_client: LLMClient | None = None


def get_client() -> LLMClient:
    """프로세스 하나에 클라이언트 하나."""
    global _client
    if _client is None:
        _client = LLMClient()
    return _client


def set_client(client: LLMClient | None) -> None:
    """테스트에서 가짜 클라이언트를 끼울 때."""
    global _client
    _client = client
