from __future__ import annotations

import pytest

from llm_proxy.domain.models import ContentBlockStartEvent, ToolUseBlock
from llm_proxy.runtime.errors import RuntimeOrchestrationError
from llm_proxy.runtime.event_log import InMemoryRuntimeEventLog
from llm_proxy.runtime.events import RuntimeEventKind
from llm_proxy.runtime.orchestrator import RuntimeOrchestrator
from llm_proxy.runtime.session_store import InMemoryRuntimeSessionStore


@pytest.fixture
def orch() -> RuntimeOrchestrator:
    return RuntimeOrchestrator(
        store=InMemoryRuntimeSessionStore(),
        log=InMemoryRuntimeEventLog(),
    )


def test_turn_start_logs_user_message(orch: RuntimeOrchestrator) -> None:
    s = orch.load_or_idle("sid")
    ns = orch.on_user_turn_start(s)
    assert ns.state.value == "executing"
    rec = orch._log.load_range("sid", 0)
    assert rec[0].kind is RuntimeEventKind.USER_MESSAGE_RECEIVED


def test_exit_plan_consumed_not_forwarded(orch: RuntimeOrchestrator) -> None:
    from llm_proxy.runtime.policies import RuntimeOrchestrationPolicies, UserMessageStartMode
    from dataclasses import replace

    orch._policies = replace(orch._policies, user_message_from_idle=UserMessageStartMode.PLANNING)
    s = orch.load_or_idle("sid")
    s = orch.on_user_turn_start(s)
    ev = ContentBlockStartEvent(
        index=0,
        block=ToolUseBlock(id="t1", name="exit_plan_mode", input={}),
    )
    s2, out = orch.process_tool_block_start(s, ev)
    assert out is None
    assert s2.state.value == "executing"


def test_bash_forwarded_in_executing(orch: RuntimeOrchestrator) -> None:
    s = orch.load_or_idle("sid")
    s = orch.on_user_turn_start(s)
    ev = ContentBlockStartEvent(
        index=0,
        block=ToolUseBlock(id="t1", name="bash", input={"command": "ls"}),
    )
    s2, out = orch.process_tool_block_start(s, ev)
    assert out is not None
    assert s2.state.value == "executing_tool"


def test_invalid_action_raises(orch: RuntimeOrchestrator) -> None:
    from llm_proxy.runtime.policies import UserMessageStartMode
    from dataclasses import replace

    orch._policies = replace(orch._policies, user_message_from_idle=UserMessageStartMode.PLANNING)
    s = orch.load_or_idle("sid")
    s = orch.on_user_turn_start(s)
    # Ordinary read_file in PLANNING is an invalid transition (tool call not allowed there).
    ev = ContentBlockStartEvent(
        index=0,
        block=ToolUseBlock(id="t1", name="Read", input={"path": "/x"}),
    )
    with pytest.raises(RuntimeOrchestrationError):
        orch.process_tool_block_start(s, ev)
