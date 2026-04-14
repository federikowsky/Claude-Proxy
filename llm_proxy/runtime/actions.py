"""Normalized runtime actions (distinct from raw tool definitions or content blocks)."""

from __future__ import annotations

from enum import StrEnum


class NormalizedRuntimeAction(StrEnum):
    ORDINARY_TOOL_CALL = "ordinary_tool_call"
    STATE_TRANSITION_ACTION = "state_transition_action"
    APPROVAL_ACTION = "approval_action"
    PERMISSION_ACTION = "permission_action"
    ORCHESTRATION_ACTION = "orchestration_action"
    FINALIZATION_ACTION = "finalization_action"
    ABORT_ACTION = "abort_action"
    INVALID_ACTION = "invalid_action"
