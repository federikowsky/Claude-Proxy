"""Checkpoint + tail replay recovery (no guessing from raw chat history)."""

from __future__ import annotations

from typing import Any, Literal

from llm_proxy.runtime.errors import RuntimeRecoveryError
from llm_proxy.runtime.event_log import RuntimeEventLog
from llm_proxy.runtime.events import RuntimeEvent, RuntimeEventKind
from llm_proxy.runtime.policies import RuntimeOrchestrationPolicies
from llm_proxy.runtime.session_codec import session_from_dict
from llm_proxy.runtime.session_store import RuntimeSessionStore
from llm_proxy.runtime.state import SessionRuntimeState
from llm_proxy.runtime.state_machine import _INTERNAL_ONLY, apply_runtime_transition, idle_session


def replay_events(
    session_id: str,
    events: list[RuntimeEvent],
    *,
    policies: RuntimeOrchestrationPolicies,
    base: SessionRuntimeState | None = None,
) -> SessionRuntimeState:
    """Deterministically rebuild session by applying persisted input events in order."""
    state = base or idle_session(session_id)
    if state.session_id != session_id:
        raise RuntimeRecoveryError("session_id mismatch", details={"expected": session_id})
    for record in sorted(events, key=lambda e: e.seq):
        if record.kind in _INTERNAL_ONLY:
            continue
        state, _ = apply_runtime_transition(state, record.kind, dict(record.payload), policies=policies)
    return state


def restore_checkpoint_then_replay_tail(
    checkpoint: SessionRuntimeState,
    events: list[RuntimeEvent],
    *,
    policies: RuntimeOrchestrationPolicies,
) -> SessionRuntimeState:
    """Start from frozen checkpoint snapshot, apply only events with seq > checkpoint.checkpoint_seq."""
    tail = [e for e in events if e.seq > checkpoint.checkpoint_seq]
    return replay_events(checkpoint.session_id, tail, policies=policies, base=checkpoint)


def build_recovery_completed_payload(session: SessionRuntimeState) -> dict[str, Any]:
    """Payload for RECOVERY_COMPLETED transition after rebuild validation."""
    return {
        "restored_state": session.state.value,
        "unresolved_subtasks": session.unresolved_subtasks,
        "in_flight_tool_id": session.in_flight_tool_id,
        "subtask_ids": list(session.subtask_ids),
        "pending_approval": _pending_approval_dict(session),
        "pending_permission": _pending_permission_dict(session),
    }


def _pending_approval_dict(session: SessionRuntimeState) -> dict[str, Any] | None:
    pa = session.pending_approval
    if pa is None:
        return None
    return {
        "approval_id": pa.approval_id,
        "resume_state": pa.resume_state.value,
        "tool_name": pa.tool_name,
        "payload": dict(pa.payload),
    }


def _pending_permission_dict(session: SessionRuntimeState) -> dict[str, Any] | None:
    pp = session.pending_permission
    if pp is None:
        return None
    return {
        "permission_id": pp.permission_id,
        "resume_state": pp.resume_state.value,
        "tool_name": pp.tool_name,
        "payload": dict(pp.payload),
    }


def append_checkpoint_event(log: RuntimeEventLog, session: SessionRuntimeState) -> RuntimeEvent:
    from llm_proxy.runtime.session_codec import session_to_dict

    snap = build_recovery_completed_payload(session)
    snap["checkpoint_seq"] = session.checkpoint_seq
    snap["session_snapshot"] = session_to_dict(session)
    return log.append(session.session_id, RuntimeEventKind.SESSION_CHECKPOINT_CREATED, snap)


def replay_persisted_session(
    session_id: str,
    *,
    log: RuntimeEventLog,
    store: RuntimeSessionStore,
    policies: RuntimeOrchestrationPolicies,
    mode: Literal["full", "from_checkpoint"],
) -> SessionRuntimeState:
    """Rebuild session from durable log; persists result to *store*."""
    events = list(log.load_range(session_id, 0))
    if mode == "full":
        state = replay_events(session_id, events, policies=policies)
        store.put(state)
        return state
    last_ck: RuntimeEvent | None = None
    for ev in reversed(events):
        if ev.kind is RuntimeEventKind.SESSION_CHECKPOINT_CREATED:
            last_ck = ev
            break
    if last_ck is None:
        raise RuntimeRecoveryError(
            "no checkpoint found for session",
            details={"session_id": session_id},
        )
    snap = last_ck.payload.get("session_snapshot")
    if not isinstance(snap, dict):
        raise RuntimeRecoveryError(
            "checkpoint missing session_snapshot",
            details={"session_id": session_id},
        )
    base = session_from_dict(snap)
    tail = [e for e in events if e.seq > last_ck.seq]
    state = replay_events(session_id, tail, policies=policies, base=base)
    store.put(state)
    return state
