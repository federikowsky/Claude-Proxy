"""Deterministic runtime transition validation and application."""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any

from llm_proxy.runtime.errors import InvalidRuntimeTransitionError
from llm_proxy.runtime.events import RuntimeEventKind
from llm_proxy.runtime.invariants import assert_runtime_invariants
from llm_proxy.runtime.policies import (
    PermissionDeniedResolution,
    PlanExitTarget,
    RuntimeOrchestrationPolicies,
    SubtaskFailedResolution,
    TimeoutResolution,
    ToolFailedResolution,
    UserMessageStartMode,
    UserRejectedResolution,
)
from llm_proxy.runtime.state import (
    ModeQualifiers,
    PendingApproval,
    PendingPermission,
    RuntimeState,
    SessionRuntimeState,
    sync_modes_with_state,
)

_INTERNAL_ONLY: frozenset[RuntimeEventKind] = frozenset(
    {
        RuntimeEventKind.STATE_TRANSITION_APPLIED,
        RuntimeEventKind.ACTION_REJECTED,
        RuntimeEventKind.ACTION_CONSUMED,
        RuntimeEventKind.ACTION_FORWARDED,
        RuntimeEventKind.STREAM_TERMINATED_BY_RUNTIME,
        RuntimeEventKind.SESSION_CHECKPOINT_CREATED,
    }
)

_TERMINAL: frozenset[RuntimeState] = frozenset(
    {
        RuntimeState.COMPLETED,
        RuntimeState.FAILED,
        RuntimeState.ABORTED,
    }
)


def _timeout_target_state(policies: RuntimeOrchestrationPolicies) -> RuntimeState:
    return (
        RuntimeState.INTERRUPTED
        if policies.timeout_resolution is TimeoutResolution.INTERRUPTED
        else RuntimeState.FAILED
    )


def _new_session(base: SessionRuntimeState, **kwargs: Any) -> SessionRuntimeState:
    s = replace(base, **kwargs)
    s.modes = sync_modes_with_state(s.state, s.modes)
    assert_runtime_invariants(s)
    return s


def _internal(
    *kinds: RuntimeEventKind,
) -> tuple[tuple[RuntimeEventKind, dict[str, object]], ...]:
    return tuple((k, {}) for k in kinds)


def apply_runtime_transition(
    session: SessionRuntimeState,
    kind: RuntimeEventKind,
    payload: dict[str, Any],
    *,
    policies: RuntimeOrchestrationPolicies,
) -> tuple[SessionRuntimeState, tuple[tuple[RuntimeEventKind, dict[str, object]], ...]]:
    """Apply one input event (external or model-derived). Returns new session + internal log tuples."""
    if kind in _INTERNAL_ONLY:
        raise InvalidRuntimeTransitionError(
            f"internal event {kind} cannot be applied as input",
            details={"state": session.state.value},
        )

    s = session.state
    out_internal: list[tuple[RuntimeEventKind, dict[str, object]]] = []

    if kind is RuntimeEventKind.MODEL_ABORT_PROPOSED:
        if s in _TERMINAL:
            raise InvalidRuntimeTransitionError("abort in terminal state", details={"state": s.value})
        ns = _new_session(
            session,
            state=RuntimeState.ABORTED,
            pending_approval=None,
            pending_permission=None,
            in_flight_tool_id=None,
            paused_resume_state=None,
            unresolved_subtasks=0,
            subtask_ids=(),
        )
        return ns, _internal(RuntimeEventKind.ACTION_CONSUMED, RuntimeEventKind.STATE_TRANSITION_APPLIED)

    if s in _TERMINAL and kind is RuntimeEventKind.USER_MESSAGE_RECEIVED:
        fresh = idle_session(session.session_id)
        fresh = replace(
            fresh,
            last_committed_turn_seq=session.last_committed_turn_seq + 1,
            checkpoint_seq=session.checkpoint_seq,
        )
        return apply_runtime_transition(fresh, kind, payload, policies=policies)

    # --- IDLE ---
    if s is RuntimeState.IDLE:
        if kind is RuntimeEventKind.USER_MESSAGE_RECEIVED:
            target = (
                RuntimeState.PLANNING
                if policies.user_message_from_idle is UserMessageStartMode.PLANNING
                else RuntimeState.EXECUTING
            )
            ns = _new_session(
                session,
                state=target,
                last_committed_turn_seq=session.last_committed_turn_seq + 1,
            )
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": target.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.RECOVERY_REQUESTED:
            ns = _new_session(session, state=RuntimeState.RECOVERING)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.RECOVERING.value}))
            return ns, tuple(out_internal)
        raise InvalidRuntimeTransitionError("invalid event for IDLE", details={"event": kind.value})

    # --- PLANNING ---
    if s is RuntimeState.PLANNING:
        if kind is RuntimeEventKind.MODEL_TEXT_EMITTED:
            return session, _internal(RuntimeEventKind.ACTION_CONSUMED)
        if kind is RuntimeEventKind.MODEL_REQUEST_APPROVAL_PROPOSED:
            pa = PendingApproval(
                approval_id=str(payload.get("approval_id") or uuid.uuid4().hex),
                resume_state=RuntimeState.PLANNING,
                tool_name=str(payload.get("tool_name", "")),
                payload={k: v for k, v in payload.items() if k not in {"approval_id", "tool_name"}},
            )
            ns = _new_session(session, state=RuntimeState.AWAITING_APPROVAL, pending_approval=pa)
            out_internal.extend(
                (
                    (RuntimeEventKind.ACTION_CONSUMED, {}),
                    (RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.AWAITING_APPROVAL.value}),
                )
            )
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.MODEL_EXIT_PLAN_PROPOSED:
            target = (
                RuntimeState.COMPLETING
                if policies.plan_exit_target is PlanExitTarget.COMPLETING
                else RuntimeState.EXECUTING
            )
            ns = _new_session(session, state=target)
            out_internal.extend(
                (
                    (RuntimeEventKind.ACTION_CONSUMED, {}),
                    (RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": target.value}),
                )
            )
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED, RuntimeEventKind.ACTION_CONSUMED)
        if kind is RuntimeEventKind.STREAM_INTERRUPTED:
            ns = _new_session(session, state=RuntimeState.INTERRUPTED)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.MODEL_INVALID_RUNTIME_ACTION:
            ns = _new_session(
                session,
                state=RuntimeState.FAILED,
                failure_reason=str(payload.get("reason", "invalid_runtime_action")),
            )
            return ns, _internal(RuntimeEventKind.ACTION_REJECTED, RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError("invalid event for PLANNING", details={"event": kind.value})

    # --- AWAITING_APPROVAL ---
    if s is RuntimeState.AWAITING_APPROVAL:
        pa = session.pending_approval
        if pa is None:
            raise InvalidRuntimeTransitionError("missing pending_approval")
        if kind is RuntimeEventKind.USER_APPROVED:
            ns = _new_session(
                session,
                state=pa.resume_state,
                pending_approval=None,
            )
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": pa.resume_state.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.USER_REJECTED:
            res = policies.user_rejected
            if res is UserRejectedResolution.ABORTED:
                ns = _new_session(
                    session,
                    state=RuntimeState.ABORTED,
                    pending_approval=None,
                    unresolved_subtasks=0,
                    subtask_ids=(),
                )
            elif res is UserRejectedResolution.PAUSED:
                ns = _new_session(
                    session,
                    state=RuntimeState.PAUSED,
                    pending_approval=None,
                    paused_resume_state=pa.resume_state,
                )
            else:
                ns = _new_session(session, state=RuntimeState.PLANNING, pending_approval=None)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": ns.state.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED, pending_approval=None)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.TIMEOUT_OCCURRED:
            tgt = _timeout_target_state(policies)
            ns = _new_session(
                session,
                state=tgt,
                pending_approval=None,
                failure_reason="timeout" if tgt is RuntimeState.FAILED else None,
            )
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError("invalid event for AWAITING_APPROVAL", details={"event": kind.value})

    # --- AWAITING_PERMISSION ---
    if s is RuntimeState.AWAITING_PERMISSION:
        pp = session.pending_permission
        if pp is None:
            raise InvalidRuntimeTransitionError("missing pending_permission")
        if kind is RuntimeEventKind.USER_PERMISSION_GRANTED:
            ns = _new_session(session, state=RuntimeState.EXECUTING, pending_permission=None)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.EXECUTING.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.USER_PERMISSION_DENIED:
            res = policies.permission_denied
            if res is PermissionDeniedResolution.ABORTED:
                ns = _new_session(session, state=RuntimeState.ABORTED, pending_permission=None)
            elif res is PermissionDeniedResolution.PLANNING:
                ns = _new_session(session, state=RuntimeState.PLANNING, pending_permission=None)
            else:
                ns = _new_session(
                    session,
                    state=RuntimeState.PAUSED,
                    pending_permission=None,
                    paused_resume_state=pp.resume_state,
                )
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": ns.state.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED, pending_permission=None)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.TIMEOUT_OCCURRED:
            tgt = _timeout_target_state(policies)
            ns = _new_session(
                session,
                state=tgt,
                pending_permission=None,
                failure_reason="timeout" if tgt is RuntimeState.FAILED else None,
            )
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError(
            "invalid event for AWAITING_PERMISSION",
            details={"event": kind.value},
        )

    # --- EXECUTING ---
    if s is RuntimeState.EXECUTING:
        if kind is RuntimeEventKind.MODEL_ENTER_PLAN_PROPOSED:
            ns = _new_session(session, state=RuntimeState.PLANNING)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.PLANNING.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.MODEL_TEXT_EMITTED:
            return session, _internal(RuntimeEventKind.ACTION_CONSUMED)
        if kind in (
            RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED,
            RuntimeEventKind.TOOL_EXECUTION_STARTED,
        ):
            tid = str(payload.get("tool_use_id") or payload.get("id") or uuid.uuid4().hex)
            ns = _new_session(
                session,
                state=RuntimeState.EXECUTING_TOOL,
                in_flight_tool_id=tid,
            )
            fwd = RuntimeEventKind.ACTION_FORWARDED if kind is RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED else RuntimeEventKind.ACTION_CONSUMED
            out_internal.extend(
                (
                    (fwd, {"tool_use_id": tid}),
                    (RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.EXECUTING_TOOL.value}),
                )
            )
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.MODEL_REQUEST_APPROVAL_PROPOSED:
            pa = PendingApproval(
                approval_id=str(payload.get("approval_id") or uuid.uuid4().hex),
                resume_state=RuntimeState.EXECUTING,
                tool_name=str(payload.get("tool_name", "")),
                payload={},
            )
            ns = _new_session(session, state=RuntimeState.AWAITING_APPROVAL, pending_approval=pa)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.AWAITING_APPROVAL.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.MODEL_REQUEST_PERMISSION_PROPOSED:
            pp = PendingPermission(
                permission_id=str(payload.get("permission_id") or uuid.uuid4().hex),
                resume_state=RuntimeState.EXECUTING,
                tool_name=str(payload.get("tool_name", "")),
                payload={},
            )
            ns = _new_session(session, state=RuntimeState.AWAITING_PERMISSION, pending_permission=pp)
            out_internal.append(
                (RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.AWAITING_PERMISSION.value})
            )
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.MODEL_START_SUBTASK_PROPOSED:
            sid = str(payload.get("subtask_id") or uuid.uuid4().hex)
            n_sub = session.unresolved_subtasks + 1
            sub_ids = session.subtask_ids + (sid,)
            ns = _new_session(
                session,
                state=RuntimeState.ORCHESTRATING,
                unresolved_subtasks=n_sub,
                subtask_ids=sub_ids,
            )
            out_internal.extend(
                (
                    (RuntimeEventKind.ACTION_CONSUMED, {}),
                    (RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.ORCHESTRATING.value}),
                )
            )
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.MODEL_COMPLETE_PROPOSED:
            ns = _new_session(session, state=RuntimeState.COMPLETING)
            out_internal.extend(
                (
                    (RuntimeEventKind.ACTION_CONSUMED, {}),
                    (RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.COMPLETING.value}),
                )
            )
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_PAUSE_REQUESTED:
            ns = _new_session(
                session,
                state=RuntimeState.PAUSED,
                paused_resume_state=RuntimeState.EXECUTING,
            )
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.PAUSED.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.STREAM_INTERRUPTED:
            ns = _new_session(session, state=RuntimeState.INTERRUPTED)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.MODEL_INVALID_RUNTIME_ACTION:
            ns = _new_session(session, state=RuntimeState.FAILED, failure_reason=str(payload.get("reason", kind.value)))
            out_internal.append((RuntimeEventKind.ACTION_REJECTED, dict(payload)))
            return ns, tuple(out_internal)
        raise InvalidRuntimeTransitionError("invalid event for EXECUTING", details={"event": kind.value})

    # --- EXECUTING_TOOL ---
    if s is RuntimeState.EXECUTING_TOOL:
        if kind is RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED:
            ns = _new_session(session, state=RuntimeState.EXECUTING, in_flight_tool_id=None)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.EXECUTING.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.TOOL_EXECUTION_FAILED:
            if policies.tool_failed is ToolFailedResolution.FAILED:
                ns = _new_session(
                    session,
                    state=RuntimeState.FAILED,
                    in_flight_tool_id=None,
                    failure_reason=str(payload.get("reason", "tool_failed")),
                )
            else:
                ns = _new_session(session, state=RuntimeState.EXECUTING, in_flight_tool_id=None)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": ns.state.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED, in_flight_tool_id=None)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError("invalid event for EXECUTING_TOOL", details={"event": kind.value})

    # --- ORCHESTRATING ---
    if s is RuntimeState.ORCHESTRATING:
        if kind is RuntimeEventKind.SUBTASK_STARTED:
            ns = _new_session(session, state=RuntimeState.AWAITING_SUBTASK)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.AWAITING_SUBTASK.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.MODEL_TEXT_EMITTED:
            return session, _internal(RuntimeEventKind.ACTION_CONSUMED)
        if kind is RuntimeEventKind.MODEL_COMPLETE_PROPOSED:
            if session.unresolved_subtasks > 0:
                raise InvalidRuntimeTransitionError(
                    "MODEL_COMPLETE_PROPOSED blocked: unresolved subtasks",
                    details={"subtasks": session.unresolved_subtasks},
                )
            ns = _new_session(session, state=RuntimeState.COMPLETING)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.COMPLETING.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError("invalid event for ORCHESTRATING", details={"event": kind.value})

    # --- AWAITING_SUBTASK ---
    if s is RuntimeState.AWAITING_SUBTASK:
        if kind is RuntimeEventKind.SUBTASK_COMPLETED:
            n_sub = max(0, session.unresolved_subtasks - 1)
            next_state = RuntimeState.ORCHESTRATING if n_sub > 0 else RuntimeState.EXECUTING
            sid = str(payload.get("subtask_id", ""))
            ids = list(session.subtask_ids)
            if sid and sid in ids:
                ids.remove(sid)
            elif ids:
                ids.pop()
            ns = _new_session(
                session,
                state=next_state,
                unresolved_subtasks=n_sub,
                subtask_ids=tuple(ids),
            )
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": next_state.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SUBTASK_FAILED:
            if policies.subtask_failed is SubtaskFailedResolution.FAILED:
                ns = _new_session(
                    session,
                    state=RuntimeState.FAILED,
                    failure_reason=str(payload.get("reason", "subtask_failed")),
                    unresolved_subtasks=0,
                    subtask_ids=(),
                )
            else:
                n_sub = max(0, session.unresolved_subtasks - 1)
                next_state = RuntimeState.ORCHESTRATING if n_sub > 0 else RuntimeState.EXECUTING
                sid = str(payload.get("subtask_id", ""))
                ids = list(session.subtask_ids)
                if sid and sid in ids:
                    ids.remove(sid)
                elif ids:
                    ids.pop()
                ns = _new_session(
                    session,
                    state=next_state,
                    unresolved_subtasks=n_sub,
                    subtask_ids=tuple(ids),
                )
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": ns.state.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.TIMEOUT_OCCURRED:
            tgt = _timeout_target_state(policies)
            ns = _new_session(
                session,
                state=tgt,
                failure_reason="timeout" if tgt is RuntimeState.FAILED else None,
                unresolved_subtasks=0,
                subtask_ids=(),
            )
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError("invalid event for AWAITING_SUBTASK", details={"event": kind.value})

    # --- PAUSED ---
    if s is RuntimeState.PAUSED:
        if kind is RuntimeEventKind.SESSION_RESUME_REQUESTED:
            rs = session.paused_resume_state or RuntimeState.EXECUTING
            ns = _new_session(session, state=rs, paused_resume_state=None)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": rs.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED, paused_resume_state=None)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.RECOVERY_REQUESTED:
            ns = _new_session(session, state=RuntimeState.RECOVERING, paused_resume_state=None)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError("invalid event for PAUSED", details={"event": kind.value})

    # --- COMPLETING ---
    if s is RuntimeState.COMPLETING:
        if kind is RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED and bool(payload.get("finalize")):
            ns = _new_session(session, state=RuntimeState.COMPLETED)
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.COMPLETED.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.TOOL_EXECUTION_FAILED and bool(payload.get("finalize")):
            ns = _new_session(
                session,
                state=RuntimeState.FAILED,
                failure_reason=str(payload.get("reason", "finalization_failed")),
            )
            out_internal.append((RuntimeEventKind.STATE_TRANSITION_APPLIED, {"to": RuntimeState.FAILED.value}))
            return ns, tuple(out_internal)
        raise InvalidRuntimeTransitionError("invalid event for COMPLETING", details={"event": kind.value})

    # --- INTERRUPTED ---
    if s is RuntimeState.INTERRUPTED:
        if kind is RuntimeEventKind.RECOVERY_REQUESTED:
            ns = _new_session(session, state=RuntimeState.RECOVERING)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        if kind is RuntimeEventKind.SESSION_ABORT_REQUESTED:
            ns = _new_session(session, state=RuntimeState.ABORTED)
            return ns, _internal(RuntimeEventKind.STATE_TRANSITION_APPLIED)
        raise InvalidRuntimeTransitionError("invalid event for INTERRUPTED", details={"event": kind.value})

    # --- RECOVERING ---
    if s is RuntimeState.RECOVERING:
        if kind is RuntimeEventKind.RECOVERY_COMPLETED:
            restored = str(payload.get("restored_state", RuntimeState.EXECUTING.value))
            try:
                rs = RuntimeState(restored)
            except ValueError as exc:
                raise InvalidRuntimeTransitionError("invalid restored_state", details={"value": restored}) from exc
            ift = payload.get("in_flight_tool_id")
            ns = _new_session(
                session,
                state=rs,
                unresolved_subtasks=int(payload.get("unresolved_subtasks", 0)),
                in_flight_tool_id=ift if isinstance(ift, str) or ift is None else str(ift),
                pending_approval=_restore_pending(payload.get("pending_approval")),
                pending_permission=_restore_pending_perm(payload.get("pending_permission")),
                subtask_ids=tuple(payload.get("subtask_ids", ())),  # type: ignore[arg-type]
            )
            out_internal.append((RuntimeEventKind.RECOVERY_COMPLETED, {"restored": rs.value}))
            return ns, tuple(out_internal)
        if kind is RuntimeEventKind.RECOVERY_FAILED:
            ns = _new_session(session, state=RuntimeState.FAILED, failure_reason="recovery_failed")
            return ns, _internal(RuntimeEventKind.RECOVERY_FAILED)
        raise InvalidRuntimeTransitionError("invalid event for RECOVERING", details={"event": kind.value})

    # --- terminal ---
    if s in (RuntimeState.COMPLETED, RuntimeState.FAILED, RuntimeState.ABORTED):
        raise InvalidRuntimeTransitionError("session is terminal", details={"state": s.value})

    raise InvalidRuntimeTransitionError("unhandled state", details={"state": s.value})


def _restore_pending(raw: object) -> PendingApproval | None:
    if not isinstance(raw, dict):
        return None
    return PendingApproval(
        approval_id=str(raw.get("approval_id", "")),
        resume_state=RuntimeState(str(raw.get("resume_state", RuntimeState.PLANNING.value))),
        tool_name=str(raw.get("tool_name", "")),
        payload=dict(raw.get("payload", {})) if isinstance(raw.get("payload"), dict) else {},
    )


def _restore_pending_perm(raw: object) -> PendingPermission | None:
    if not isinstance(raw, dict):
        return None
    return PendingPermission(
        permission_id=str(raw.get("permission_id", "")),
        resume_state=RuntimeState(str(raw.get("resume_state", RuntimeState.EXECUTING.value))),
        tool_name=str(raw.get("tool_name", "")),
        payload=dict(raw.get("payload", {})) if isinstance(raw.get("payload"), dict) else {},
    )


def idle_session(session_id: str) -> SessionRuntimeState:
    s = SessionRuntimeState(
        session_id=session_id,
        state=RuntimeState.IDLE,
        modes=sync_modes_with_state(RuntimeState.IDLE, ModeQualifiers()),
        pending_approval=None,
        pending_permission=None,
        in_flight_tool_id=None,
        unresolved_subtasks=0,
        subtask_ids=(),
        paused_resume_state=None,
        last_committed_turn_seq=0,
        checkpoint_seq=0,
    )
    assert_runtime_invariants(s)
    return s
