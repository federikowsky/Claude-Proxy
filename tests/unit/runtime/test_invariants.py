from __future__ import annotations

import pytest

from claude_proxy.runtime.errors import RuntimeInvariantViolationError
from claude_proxy.runtime.invariants import assert_runtime_invariants
from claude_proxy.runtime.state import (
    ModeQualifiers,
    PendingApproval,
    PendingPermission,
    RuntimeState,
    SessionRuntimeState,
    sync_modes_with_state,
)


def _session(**kwargs) -> SessionRuntimeState:
    defaults = dict(
        session_id="x",
        state=RuntimeState.EXECUTING,
        modes=sync_modes_with_state(RuntimeState.EXECUTING, ModeQualifiers()),
        pending_approval=None,
        pending_permission=None,
        in_flight_tool_id=None,
        unresolved_subtasks=0,
        subtask_ids=(),
        paused_resume_state=None,
        last_committed_turn_seq=0,
        checkpoint_seq=0,
    )
    defaults.update(kwargs)
    return SessionRuntimeState(**defaults)  # type: ignore[arg-type]


def test_terminal_skips_strict_invariants() -> None:
    s = _session(state=RuntimeState.ABORTED, unresolved_subtasks=99)
    assert_runtime_invariants(s)


def test_approval_mismatch_raises() -> None:
    s = _session(
        state=RuntimeState.EXECUTING,
        pending_approval=PendingApproval("a", RuntimeState.PLANNING),
    )
    with pytest.raises(RuntimeInvariantViolationError):
        assert_runtime_invariants(s)


def test_executing_tool_requires_in_flight() -> None:
    s = _session(state=RuntimeState.EXECUTING_TOOL, in_flight_tool_id=None)
    with pytest.raises(RuntimeInvariantViolationError):
        assert_runtime_invariants(s)


def test_orchestrating_requires_subtasks() -> None:
    s = _session(state=RuntimeState.ORCHESTRATING, unresolved_subtasks=0)
    with pytest.raises(RuntimeInvariantViolationError):
        assert_runtime_invariants(s)
