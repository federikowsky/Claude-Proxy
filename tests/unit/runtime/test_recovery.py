from __future__ import annotations

from llm_proxy.runtime.event_log import InMemoryRuntimeEventLog
from llm_proxy.runtime.events import RuntimeEvent, RuntimeEventKind
from llm_proxy.runtime.policies import RuntimeOrchestrationPolicies, UserMessageStartMode
from llm_proxy.runtime.recovery import replay_events
from llm_proxy.runtime.state import RuntimeState
from llm_proxy.runtime.state_machine import idle_session


def test_replay_rebuilds_executing_with_tool_cycle() -> None:
    pol = RuntimeOrchestrationPolicies(user_message_from_idle=UserMessageStartMode.EXECUTING)
    log = InMemoryRuntimeEventLog()
    sid = "r1"
    log.append(sid, RuntimeEventKind.USER_MESSAGE_RECEIVED, {})
    log.append(
        sid,
        RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED,
        {"tool_use_id": "x", "tool_name": "bash"},
    )
    log.append(sid, RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED, {})
    events = list(log.load_range(sid, 0))
    rebuilt = replay_events(sid, events, policies=pol)
    assert rebuilt.state is RuntimeState.EXECUTING
    assert rebuilt.in_flight_tool_id is None


def test_replay_from_checkpoint_base() -> None:
    pol = RuntimeOrchestrationPolicies()
    base = idle_session("c1")
    from dataclasses import replace
    from llm_proxy.runtime.state import sync_modes_with_state, ModeQualifiers

    base = replace(
        base,
        state=RuntimeState.EXECUTING,
        modes=sync_modes_with_state(RuntimeState.EXECUTING, ModeQualifiers()),
    )
    ev = [RuntimeEvent(0, RuntimeEventKind.MODEL_TEXT_EMITTED, {})]
    rebuilt = replay_events("c1", ev, policies=pol, base=base)
    assert rebuilt.state is RuntimeState.EXECUTING
