"""Incremental canonical-event stream integration for the runtime orchestrator."""

from __future__ import annotations

from collections.abc import AsyncIterator

from claude_proxy.domain.models import (
    CanonicalEvent,
    ContentBlockStartEvent,
    TextBlock,
    ToolUseBlock,
)
from claude_proxy.capabilities.signals import ToolUseSignalContext
from claude_proxy.capabilities.text_control import apply_text_control_policy
from claude_proxy.runtime.orchestrator import RuntimeOrchestrator

_STREAM_CTX = ToolUseSignalContext(delivery="stream", origin="model_tool_use")


async def runtime_orchestrate_stream(
    events: AsyncIterator[CanonicalEvent],
    *,
    orchestrator: RuntimeOrchestrator,
    session_id: str,
) -> AsyncIterator[CanonicalEvent]:
    """Apply runtime classification + state machine; yield only client-safe events."""
    session = orchestrator.load_or_idle(session_id)
    session = orchestrator.on_user_turn_start(session)
    try:
        async for ev in events:
            if isinstance(ev, ContentBlockStartEvent):
                if isinstance(ev.block, ToolUseBlock):
                    session, out = orchestrator.process_tool_block_start(
                        session,
                        ev,
                        signal_context=_STREAM_CTX,
                    )
                    if out is not None:
                        yield out
                    continue
                if isinstance(ev.block, TextBlock):
                    apply_text_control_policy(
                        text=ev.block.text,
                        policy=orchestrator.policies.text_control_attempt_policy,
                    )
                    session = orchestrator.on_model_text_block_started(session)
                    yield ev
                    continue
            yield ev
    finally:
        orchestrator.log_stream_terminated(session)
