"""Typed runtime event kinds (external, model-derived, internal)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class RuntimeEventKind(StrEnum):
    """All runtime events processed by the state machine."""

    # --- external ---
    USER_MESSAGE_RECEIVED = "user_message_received"
    USER_APPROVED = "user_approved"
    USER_REJECTED = "user_rejected"
    USER_PERMISSION_GRANTED = "user_permission_granted"
    USER_PERMISSION_DENIED = "user_permission_denied"
    TOOL_EXECUTION_STARTED = "tool_execution_started"
    TOOL_EXECUTION_SUCCEEDED = "tool_execution_succeeded"
    TOOL_EXECUTION_FAILED = "tool_execution_failed"
    SUBTASK_STARTED = "subtask_started"
    SUBTASK_COMPLETED = "subtask_completed"
    SUBTASK_FAILED = "subtask_failed"
    SESSION_ABORT_REQUESTED = "session_abort_requested"
    SESSION_PAUSE_REQUESTED = "session_pause_requested"
    SESSION_RESUME_REQUESTED = "session_resume_requested"
    STREAM_INTERRUPTED = "stream_interrupted"
    RECOVERY_REQUESTED = "recovery_requested"
    TIMEOUT_OCCURRED = "timeout_occurred"

    # --- model-derived ---
    MODEL_TEXT_EMITTED = "model_text_emitted"
    MODEL_TOOL_CALL_PROPOSED = "model_tool_call_proposed"
    MODEL_ENTER_PLAN_PROPOSED = "model_enter_plan_proposed"
    MODEL_EXIT_PLAN_PROPOSED = "model_exit_plan_proposed"
    MODEL_REQUEST_APPROVAL_PROPOSED = "model_request_approval_proposed"
    MODEL_REQUEST_PERMISSION_PROPOSED = "model_request_permission_proposed"
    MODEL_START_SUBTASK_PROPOSED = "model_start_subtask_proposed"
    MODEL_COMPLETE_PROPOSED = "model_complete_proposed"
    MODEL_ABORT_PROPOSED = "model_abort_proposed"
    MODEL_INVALID_RUNTIME_ACTION = "model_invalid_runtime_action"

    # --- internal ---
    STATE_TRANSITION_APPLIED = "state_transition_applied"
    ACTION_REJECTED = "action_rejected"
    ACTION_CONSUMED = "action_consumed"
    ACTION_FORWARDED = "action_forwarded"
    STREAM_TERMINATED_BY_RUNTIME = "stream_terminated_by_runtime"
    SESSION_CHECKPOINT_CREATED = "session_checkpoint_created"
    RECOVERY_COMPLETED = "recovery_completed"
    RECOVERY_FAILED = "recovery_failed"


@dataclass(slots=True, frozen=True)
class RuntimeEvent:
    """Append-only event record."""

    seq: int
    kind: RuntimeEventKind
    payload: dict[str, Any] = field(default_factory=dict)
