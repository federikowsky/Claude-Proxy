"""Deterministic JSON serialization for SessionRuntimeState (persistence / checkpoints)."""

from __future__ import annotations

from typing import Any

from claude_proxy.runtime.state import (
    ModeQualifiers,
    PendingApproval,
    PendingPermission,
    RuntimeState,
    SessionRuntimeState,
)


def session_to_dict(session: SessionRuntimeState) -> dict[str, Any]:
    return {
        "session_id": session.session_id,
        "state": session.state.value,
        "pending_approval": _approval_to_dict(session.pending_approval),
        "pending_permission": _permission_to_dict(session.pending_permission),
        "in_flight_tool_id": session.in_flight_tool_id,
        "unresolved_subtasks": session.unresolved_subtasks,
        "subtask_ids": list(session.subtask_ids),
        "paused_resume_state": session.paused_resume_state.value if session.paused_resume_state else None,
        "last_committed_turn_seq": session.last_committed_turn_seq,
        "checkpoint_seq": session.checkpoint_seq,
        "failure_reason": session.failure_reason,
    }


def session_from_dict(data: dict[str, Any]) -> SessionRuntimeState:
    pr = data.get("paused_resume_state")
    return SessionRuntimeState(
        session_id=str(data["session_id"]),
        state=RuntimeState(str(data["state"])),
        modes=ModeQualifiers(),
        pending_approval=_approval_from_dict(data.get("pending_approval")),
        pending_permission=_permission_from_dict(data.get("pending_permission")),
        in_flight_tool_id=data.get("in_flight_tool_id"),
        unresolved_subtasks=int(data.get("unresolved_subtasks", 0)),
        subtask_ids=tuple(str(x) for x in (data.get("subtask_ids") or [])),
        paused_resume_state=RuntimeState(str(pr)) if pr else None,
        last_committed_turn_seq=int(data.get("last_committed_turn_seq", 0)),
        checkpoint_seq=int(data.get("checkpoint_seq", 0)),
        failure_reason=data.get("failure_reason"),
    )


def _approval_to_dict(pa: PendingApproval | None) -> dict[str, Any] | None:
    if pa is None:
        return None
    return {
        "approval_id": pa.approval_id,
        "resume_state": pa.resume_state.value,
        "tool_name": pa.tool_name,
        "payload": dict(pa.payload),
    }


def _permission_to_dict(pp: PendingPermission | None) -> dict[str, Any] | None:
    if pp is None:
        return None
    return {
        "permission_id": pp.permission_id,
        "resume_state": pp.resume_state.value,
        "tool_name": pp.tool_name,
        "payload": dict(pp.payload),
    }


def _approval_from_dict(raw: object) -> PendingApproval | None:
    if not isinstance(raw, dict):
        return None
    return PendingApproval(
        approval_id=str(raw.get("approval_id", "")),
        resume_state=RuntimeState(str(raw.get("resume_state", RuntimeState.PLANNING.value))),
        tool_name=str(raw.get("tool_name", "")),
        payload=dict(raw["payload"]) if isinstance(raw.get("payload"), dict) else {},
    )


def _permission_from_dict(raw: object) -> PendingPermission | None:
    if not isinstance(raw, dict):
        return None
    return PendingPermission(
        permission_id=str(raw.get("permission_id", "")),
        resume_state=RuntimeState(str(raw.get("resume_state", RuntimeState.EXECUTING.value))),
        tool_name=str(raw.get("tool_name", "")),
        payload=dict(raw["payload"]) if isinstance(raw.get("payload"), dict) else {},
    )
