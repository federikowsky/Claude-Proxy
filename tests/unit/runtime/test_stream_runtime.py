from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

import pytest

from llm_proxy.domain.models import ContentBlockStartEvent, MessageStartEvent, TextBlock, ToolUseBlock
from llm_proxy.domain.enums import Role
from llm_proxy.domain.models import ChatResponse, Usage
from llm_proxy.runtime.event_log import InMemoryRuntimeEventLog
from llm_proxy.runtime.orchestrator import RuntimeOrchestrator
from llm_proxy.runtime.session_store import InMemoryRuntimeSessionStore
from llm_proxy.runtime.stream import runtime_orchestrate_stream


async def _src(*events) -> AsyncIterator:
    for e in events:
        await asyncio.sleep(0)
        yield e


@pytest.mark.asyncio
async def test_stream_pulls_incrementally() -> None:
    stages: list[str] = []

    async def staged():
        stages.append("m")
        yield MessageStartEvent(
            message=ChatResponse(
                id="1",
                role=Role.ASSISTANT,
                model="m",
                content=(),
                stop_reason=None,
                stop_sequence=None,
                usage=Usage(),
            )
        )
        await asyncio.sleep(0)
        stages.append("t")
        yield ContentBlockStartEvent(index=0, block=TextBlock(text=""))

    orch = RuntimeOrchestrator(store=InMemoryRuntimeSessionStore(), log=InMemoryRuntimeEventLog())
    out = runtime_orchestrate_stream(staged(), orchestrator=orch, session_id="lazy")
    assert stages == []
    a = await out.__anext__()
    assert isinstance(a, MessageStartEvent)
    assert stages == ["m"]
    b = await out.__anext__()
    assert isinstance(b, ContentBlockStartEvent)
    assert stages == ["m", "t"]
