"""Map typed Settings models to frozen RuntimeOrchestrationPolicies."""

from __future__ import annotations

from claude_proxy.infrastructure.config import RuntimeOrchestrationPolicySettings
from claude_proxy.capabilities.enums import TextControlAttemptPolicy
from claude_proxy.runtime.policies import (
    InteractiveInputRepairMode,
    PermissionDeniedResolution,
    PlanExitTarget,
    RuntimeOrchestrationPolicies,
    SubtaskFailedResolution,
    TimeoutResolution,
    ToolFailedResolution,
    UserMessageStartMode,
    UserRejectedResolution,
)


def policies_from_settings(settings: RuntimeOrchestrationPolicySettings) -> RuntimeOrchestrationPolicies:
    return RuntimeOrchestrationPolicies(
        user_message_from_idle=UserMessageStartMode(settings.user_message_from_idle),
        plan_exit_target=PlanExitTarget(settings.plan_exit_target),
        user_rejected=UserRejectedResolution(settings.user_rejected),
        permission_denied=PermissionDeniedResolution(settings.permission_denied),
        tool_failed=ToolFailedResolution(settings.tool_failed),
        subtask_failed=SubtaskFailedResolution(settings.subtask_failed),
        timeout_resolution=TimeoutResolution(settings.timeout_resolution),
        interactive_input_repair=InteractiveInputRepairMode(settings.interactive_input_repair),
        text_control_attempt_policy=TextControlAttemptPolicy(settings.text_control_attempt_policy),
    )
