"""Session invariant validation (deterministic, no guessing)."""

from __future__ import annotations

from claude_proxy.runtime.errors import RuntimeInvariantViolationError
from claude_proxy.runtime.state import RuntimeState, SessionRuntimeState


def assert_runtime_invariants(session: SessionRuntimeState) -> None:
    """Raise if session violates documented orchestration invariants."""
    s = session.state
    if s in (
        RuntimeState.COMPLETED,
        RuntimeState.FAILED,
        RuntimeState.ABORTED,
    ):
        return
    if session.pending_approval is not None and s is not RuntimeState.AWAITING_APPROVAL:
        raise RuntimeInvariantViolationError(
            "pending_approval requires AWAITING_APPROVAL",
            details={"state": s.value},
        )
    if session.pending_approval is None and s is RuntimeState.AWAITING_APPROVAL:
        raise RuntimeInvariantViolationError(
            "AWAITING_APPROVAL requires pending_approval",
            details={"state": s.value},
        )
    if session.pending_permission is not None and s is not RuntimeState.AWAITING_PERMISSION:
        raise RuntimeInvariantViolationError(
            "pending_permission requires AWAITING_PERMISSION",
            details={"state": s.value},
        )
    if session.pending_permission is None and s is RuntimeState.AWAITING_PERMISSION:
        raise RuntimeInvariantViolationError(
            "AWAITING_PERMISSION requires pending_permission",
            details={"state": s.value},
        )
    if session.in_flight_tool_id is not None and s is not RuntimeState.EXECUTING_TOOL:
        raise RuntimeInvariantViolationError(
            "in_flight_tool_id requires EXECUTING_TOOL",
            details={"state": s.value},
        )
    if session.in_flight_tool_id is None and s is RuntimeState.EXECUTING_TOOL:
        raise RuntimeInvariantViolationError(
            "EXECUTING_TOOL requires in_flight_tool_id",
            details={"state": s.value},
        )
    if session.unresolved_subtasks > 0 and s not in (
        RuntimeState.ORCHESTRATING,
        RuntimeState.AWAITING_SUBTASK,
    ):
        raise RuntimeInvariantViolationError(
            "unresolved_subtasks>0 requires ORCHESTRATING or AWAITING_SUBTASK",
            details={"state": s.value, "subtasks": session.unresolved_subtasks},
        )
    if session.unresolved_subtasks <= 0 and s in (
        RuntimeState.ORCHESTRATING,
        RuntimeState.AWAITING_SUBTASK,
    ):
        raise RuntimeInvariantViolationError(
            "ORCHESTRATING/AWAITING_SUBTASK require unresolved_subtasks>0",
            details={"state": s.value, "subtasks": session.unresolved_subtasks},
        )
    if session.paused_resume_state is not None and s is not RuntimeState.PAUSED:
        raise RuntimeInvariantViolationError(
            "paused_resume_state only valid in PAUSED",
            details={"state": s.value},
        )
