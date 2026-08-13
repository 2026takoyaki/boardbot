"""테스트 공통 설정."""

from __future__ import annotations

import pytest


@pytest.fixture
def anyio_backend() -> str:
    """anyio 테스트를 asyncio에서만 돌린다.

    기본값이면 anyio가 asyncio와 trio 양쪽으로 같은 테스트를 돌리는데, FSM 타이머가
    `asyncio.create_task`를 쓰므로 trio 백엔드에서는 이벤트 루프가 없다며 반드시
    깨진다("RuntimeError: no running event loop"). 서버가 FastAPI/uvicorn = asyncio
    전용이라 trio에서 도는 것 자체가 검증 대상이 아니다.
    """
    return "asyncio"
