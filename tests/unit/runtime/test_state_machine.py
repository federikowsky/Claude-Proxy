from __future__ import annotations

from dataclasses import replace

import pytest

from claude_proxy.runtime.errors import InvalidRuntimeTransitionError
from claude_proxy.runtime.events import RuntimeEventKind
from claude_proxy.runtime.policies import (
    RuntimeOrchestrationPolicies,
    UserMessageStartMode,
    PlanExitTarget,
    UserRejectedResolution,
    PermissionDeniedResolution,
    ToolFailedResolution,
    SubtaskFailedResolution,
)
from claude_proxy.runtime.state import RuntimeState
from claude_proxy.runtime.state_machine import apply_runtime_transition, idle_session


def _p(**kwargs) -> RuntimeOrchestrationPolicies:
    base = RuntimeOrchestrationPolicies()
    return replace(base, **kwargs) if kwargs else base


def test_idle_user_message_to_executing_default() -> None:
    s = idle_session("s1")
    pol = _p()
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    assert ns.state is RuntimeState.EXECUTING


def test_idle_user_message_to_planning() -> None:
    s = idle_session("s1")
    pol = _p(user_message_from_idle=UserMessageStartMode.PLANNING)
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    assert ns.state is RuntimeState.PLANNING


def test_planning_exit_to_executing() -> None:
    s = idle_session("s1")
    pol = _p(user_message_from_idle=UserMessageStartMode.PLANNING, plan_exit_target=PlanExitTarget.EXECUTING)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.MODEL_EXIT_PLAN_PROPOSED, {}, policies=pol)
    assert ns.state is RuntimeState.EXECUTING


def test_executing_tool_proposal_to_executing_tool() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    ns, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED,
        {"tool_use_id": "t1", "tool_name": "bash"},
        policies=pol,
    )
    assert ns.state is RuntimeState.EXECUTING_TOOL
    assert ns.in_flight_tool_id == "t1"


def test_executing_tool_success_back_to_executing() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED,
        {"tool_use_id": "t1"},
        policies=pol,
    )
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED, {}, policies=pol)
    assert ns.state is RuntimeState.EXECUTING
    assert ns.in_flight_tool_id is None


def test_approval_lifecycle() -> None:
    s = idle_session("s1")
    pol = _p(user_message_from_idle=UserMessageStartMode.PLANNING)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_REQUEST_APPROVAL_PROPOSED,
        {"approval_id": "a1", "tool_name": "ask_user"},
        policies=pol,
    )
    assert s.state is RuntimeState.AWAITING_APPROVAL
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_APPROVED, {}, policies=pol)
    assert s.state is RuntimeState.PLANNING


def test_permission_lifecycle() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_REQUEST_PERMISSION_PROPOSED,
        {"permission_id": "p1"},
        policies=pol,
    )
    assert s.state is RuntimeState.AWAITING_PERMISSION
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_PERMISSION_GRANTED, {}, policies=pol)
    assert s.state is RuntimeState.EXECUTING


def test_delegation_subtask_flow() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_START_SUBTASK_PROPOSED,
        {"subtask_id": "st1", "tool_use_id": "tu1"},
        policies=pol,
    )
    assert s.state is RuntimeState.ORCHESTRATING
    assert s.unresolved_subtasks == 1
    s, _ = apply_runtime_transition(s, RuntimeEventKind.SUBTASK_STARTED, {}, policies=pol)
    assert s.state is RuntimeState.AWAITING_SUBTASK
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.SUBTASK_COMPLETED,
        {"subtask_id": "st1"},
        policies=pol,
    )
    assert s.state is RuntimeState.EXECUTING
    assert s.unresolved_subtasks == 0


def test_orchestrating_complete_blocked_with_open_subtasks() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_START_SUBTASK_PROPOSED,
        {"subtask_id": "st1"},
        policies=pol,
    )
    with pytest.raises(InvalidRuntimeTransitionError):
        apply_runtime_transition(s, RuntimeEventKind.MODEL_COMPLETE_PROPOSED, {}, policies=pol)


def test_completing_finalize_success() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.MODEL_COMPLETE_PROPOSED, {}, policies=pol)
    assert s.state is RuntimeState.COMPLETING
    ns, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED,
        {"finalize": True},
        policies=pol,
    )
    assert ns.state is RuntimeState.COMPLETED


def test_pause_resume_executing() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.SESSION_PAUSE_REQUESTED, {}, policies=pol)
    assert s.state is RuntimeState.PAUSED
    assert s.paused_resume_state is RuntimeState.EXECUTING
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.SESSION_RESUME_REQUESTED, {}, policies=pol)
    assert ns.state is RuntimeState.EXECUTING


def test_terminal_user_message_starts_new_turn() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.MODEL_COMPLETE_PROPOSED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED,
        {"finalize": True},
        policies=pol,
    )
    assert s.state is RuntimeState.COMPLETED
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    assert ns.state is RuntimeState.EXECUTING


def test_model_abort_from_executing() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.MODEL_ABORT_PROPOSED, {}, policies=pol)
    assert ns.state is RuntimeState.ABORTED


def test_stream_interrupted_to_recovery_path() -> None:
    s = idle_session("s1")
    pol = _p(user_message_from_idle=UserMessageStartMode.PLANNING)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.STREAM_INTERRUPTED, {}, policies=pol)
    assert s.state is RuntimeState.INTERRUPTED
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.RECOVERY_REQUESTED, {}, policies=pol)
    assert ns.state is RuntimeState.RECOVERING


def test_recovery_completed_restores_executing() -> None:
    s = idle_session("s1")
    pol = _p()
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.STREAM_INTERRUPTED, {}, policies=pol)
    assert s.state is RuntimeState.INTERRUPTED
    s, _ = apply_runtime_transition(s, RuntimeEventKind.RECOVERY_REQUESTED, {}, policies=pol)
    assert s.state is RuntimeState.RECOVERING
    ns, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.RECOVERY_COMPLETED,
        {
            "restored_state": RuntimeState.EXECUTING.value,
            "unresolved_subtasks": 0,
            "in_flight_tool_id": None,
            "subtask_ids": [],
        },
        policies=pol,
    )
    assert ns.state is RuntimeState.EXECUTING


def test_invalid_internal_event_rejected() -> None:
    s = idle_session("s1")
    pol = _p()
    with pytest.raises(InvalidRuntimeTransitionError):
        apply_runtime_transition(s, RuntimeEventKind.STATE_TRANSITION_APPLIED, {}, policies=pol)


def test_user_rejected_to_paused() -> None:
    s = idle_session("s1")
    pol = _p(user_message_from_idle=UserMessageStartMode.PLANNING, user_rejected=UserRejectedResolution.PAUSED)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_REQUEST_APPROVAL_PROPOSED,
        {"approval_id": "a1"},
        policies=pol,
    )
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.USER_REJECTED, {}, policies=pol)
    assert ns.state is RuntimeState.PAUSED


def test_permission_denied_to_planning() -> None:
    s = idle_session("s1")
    pol = _p(permission_denied=PermissionDeniedResolution.PLANNING)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_REQUEST_PERMISSION_PROPOSED,
        {"permission_id": "p1"},
        policies=pol,
    )
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.USER_PERMISSION_DENIED, {}, policies=pol)
    assert ns.state is RuntimeState.PLANNING


def test_tool_failed_policy_failed() -> None:
    s = idle_session("s1")
    pol = _p(tool_failed=ToolFailedResolution.FAILED)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED,
        {"tool_use_id": "x"},
        policies=pol,
    )
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.TOOL_EXECUTION_FAILED, {"reason": "e"}, policies=pol)
    assert ns.state is RuntimeState.FAILED


def test_subtask_failed_policy_failed() -> None:
    s = idle_session("s1")
    pol = _p(subtask_failed=SubtaskFailedResolution.FAILED)
    s, _ = apply_runtime_transition(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {}, policies=pol)
    s, _ = apply_runtime_transition(
        s,
        RuntimeEventKind.MODEL_START_SUBTASK_PROPOSED,
        {"subtask_id": "st1"},
        policies=pol,
    )
    s, _ = apply_runtime_transition(s, RuntimeEventKind.SUBTASK_STARTED, {}, policies=pol)
    ns, _ = apply_runtime_transition(s, RuntimeEventKind.SUBTASK_FAILED, {"reason": "e"}, policies=pol)
    assert ns.state is RuntimeState.FAILED
