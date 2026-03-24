"""Configurable resolution for under-specified transitions (reject / pause / abort)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from claude_proxy.capabilities.enums import TextControlAttemptPolicy
from claude_proxy.runtime.state import RuntimeState


class UserRejectedResolution(StrEnum):
    PLANNING = "planning"
    PAUSED = "paused"
    ABORTED = "aborted"


class PermissionDeniedResolution(StrEnum):
    PAUSED = "paused"
    PLANNING = "planning"
    ABORTED = "aborted"


class ToolFailedResolution(StrEnum):
    EXECUTING = "executing"
    FAILED = "failed"


class SubtaskFailedResolution(StrEnum):
    ORCHESTRATING = "orchestrating"
    FAILED = "failed"


class UserMessageStartMode(StrEnum):
    """Where USER_MESSAGE_RECEIVED lands from IDLE."""

    PLANNING = "planning"
    EXECUTING = "executing"


class PlanExitTarget(StrEnum):
    EXECUTING = "executing"
    COMPLETING = "completing"


class TimeoutResolution(StrEnum):
    """Effect of TIMEOUT_OCCURRED in blocking wait states."""

    FAILED = "failed"
    INTERRUPTED = "interrupted"


class InteractiveInputRepairMode(StrEnum):
    """How strictly to enforce SDK-shaped contracts for interactive / plan tools."""

    REPAIR = "repair"
    FORWARD_RAW = "forward_raw"
    STRICT = "strict"


@dataclass(slots=True, frozen=True)
class RuntimeOrchestrationPolicies:
    user_message_from_idle: UserMessageStartMode = UserMessageStartMode.EXECUTING
    plan_exit_target: PlanExitTarget = PlanExitTarget.EXECUTING
    user_rejected: UserRejectedResolution = UserRejectedResolution.PLANNING
    permission_denied: PermissionDeniedResolution = PermissionDeniedResolution.PAUSED
    tool_failed: ToolFailedResolution = ToolFailedResolution.EXECUTING
    subtask_failed: SubtaskFailedResolution = SubtaskFailedResolution.ORCHESTRATING
    timeout_resolution: TimeoutResolution = TimeoutResolution.FAILED
    interactive_input_repair: InteractiveInputRepairMode = InteractiveInputRepairMode.REPAIR
    text_control_attempt_policy: TextControlAttemptPolicy = TextControlAttemptPolicy.IGNORE


def approval_resume_state(pending_resume: RuntimeState) -> RuntimeState:
    return pending_resume
