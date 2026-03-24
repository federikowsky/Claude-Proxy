"""Map model artifacts to normalized actions and runtime event kinds (deterministic registry)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from claude_proxy.application.runtime_actions import RuntimeAction, RuntimeActionClassifier
from claude_proxy.domain.enums import RuntimeActionType
from claude_proxy.domain.models import TextBlock, ToolUseBlock
from claude_proxy.runtime.actions import NormalizedRuntimeAction
from claude_proxy.runtime.events import RuntimeEventKind

# Explicit control-tool → model-derived event mapping (no free-form inference).
_ABORT_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "abort",
        "abort_session",
        "session_abort",
        "end_session",
        "kill_session",
        "cancel_session",
    }
)

_CONTROL_TOOL_EVENTS: dict[str, RuntimeEventKind] = {
    "exit_plan_mode": RuntimeEventKind.MODEL_EXIT_PLAN_PROPOSED,
    "enter_plan_mode": RuntimeEventKind.MODEL_ENTER_PLAN_PROPOSED,
    "plan_mode": RuntimeEventKind.MODEL_ENTER_PLAN_PROPOSED,
    "ask_user": RuntimeEventKind.MODEL_REQUEST_APPROVAL_PROPOSED,
    "approval": RuntimeEventKind.MODEL_REQUEST_APPROVAL_PROPOSED,
    "request_permission": RuntimeEventKind.MODEL_REQUEST_PERMISSION_PROPOSED,
    "permission_request": RuntimeEventKind.MODEL_REQUEST_PERMISSION_PROPOSED,
}


@dataclass(slots=True, frozen=True)
class ModelClassification:
    normalized: NormalizedRuntimeAction
    event_kind: RuntimeEventKind
    payload: dict[str, Any]
    forward_ordinary_tool: bool


class RuntimeModelClassifier:
    """Classify canonical model outputs into orchestration events."""

    def __init__(self, base: RuntimeActionClassifier | None = None) -> None:
        self._base = base or RuntimeActionClassifier()

    def classify_tool_use(self, block: ToolUseBlock) -> ModelClassification:
        name_lower = block.name.lower()
        payload: dict[str, Any] = {
            "tool_use_id": block.id,
            "tool_name": block.name,
            "input": block.input,
        }
        if name_lower in _ABORT_TOOL_NAMES:
            return ModelClassification(
                normalized=NormalizedRuntimeAction.ABORT_ACTION,
                event_kind=RuntimeEventKind.MODEL_ABORT_PROPOSED,
                payload=payload,
                forward_ordinary_tool=False,
            )

        ra = self._base.classify(block)

        if ra.action_type is RuntimeActionType.TOOL_CALL:
            return ModelClassification(
                normalized=NormalizedRuntimeAction.ORDINARY_TOOL_CALL,
                event_kind=RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED,
                payload=payload,
                forward_ordinary_tool=True,
            )

        if ra.action_type is RuntimeActionType.FINALIZATION_ACTION:
            return ModelClassification(
                normalized=NormalizedRuntimeAction.FINALIZATION_ACTION,
                event_kind=RuntimeEventKind.MODEL_COMPLETE_PROPOSED,
                payload=payload,
                forward_ordinary_tool=False,
            )

        if ra.action_type is RuntimeActionType.ORCHESTRATION_ACTION:
            return ModelClassification(
                normalized=NormalizedRuntimeAction.ORCHESTRATION_ACTION,
                event_kind=RuntimeEventKind.MODEL_START_SUBTASK_PROPOSED,
                payload={**payload, "subtask_id": block.id},
                forward_ordinary_tool=False,
            )

        if ra.action_type is RuntimeActionType.INVALID_ACTION:
            return ModelClassification(
                normalized=NormalizedRuntimeAction.INVALID_ACTION,
                event_kind=RuntimeEventKind.MODEL_INVALID_RUNTIME_ACTION,
                payload={**payload, "reason": ra.diagnostic},
                forward_ordinary_tool=False,
            )

        if ra.action_type is RuntimeActionType.STATE_TRANSITION:
            ev = _CONTROL_TOOL_EVENTS.get(name_lower)
            if ev is not None:
                norm = (
                    NormalizedRuntimeAction.APPROVAL_ACTION
                    if ev is RuntimeEventKind.MODEL_REQUEST_APPROVAL_PROPOSED
                    else NormalizedRuntimeAction.PERMISSION_ACTION
                    if ev is RuntimeEventKind.MODEL_REQUEST_PERMISSION_PROPOSED
                    else NormalizedRuntimeAction.STATE_TRANSITION_ACTION
                )
                return ModelClassification(
                    normalized=norm,
                    event_kind=ev,
                    payload={
                        **payload,
                        "approval_id": block.id,
                        "permission_id": block.id,
                    },
                    forward_ordinary_tool=False,
                )
            # Planning artifact: treated as planning-time text signal (deterministic registry fallback).
            if name_lower == "todowrite":
                return ModelClassification(
                    normalized=NormalizedRuntimeAction.STATE_TRANSITION_ACTION,
                    event_kind=RuntimeEventKind.MODEL_TEXT_EMITTED,
                    payload={"tool_name": block.name, "kind": "todo_write"},
                    forward_ordinary_tool=False,
                )
            return ModelClassification(
                normalized=NormalizedRuntimeAction.STATE_TRANSITION_ACTION,
                event_kind=RuntimeEventKind.MODEL_INVALID_RUNTIME_ACTION,
                payload={**payload, "reason": ra.diagnostic},
                forward_ordinary_tool=False,
            )

        if ra.action_type is RuntimeActionType.NO_OP:
            return ModelClassification(
                normalized=NormalizedRuntimeAction.INVALID_ACTION,
                event_kind=RuntimeEventKind.MODEL_TEXT_EMITTED,
                payload={},
                forward_ordinary_tool=False,
            )

        return ModelClassification(
            normalized=NormalizedRuntimeAction.INVALID_ACTION,
            event_kind=RuntimeEventKind.MODEL_INVALID_RUNTIME_ACTION,
            payload={**payload, "reason": "unclassified_action"},
            forward_ordinary_tool=False,
        )

    @staticmethod
    def text_emitted(_block: TextBlock) -> ModelClassification:
        return ModelClassification(
            normalized=NormalizedRuntimeAction.STATE_TRANSITION_ACTION,
            event_kind=RuntimeEventKind.MODEL_TEXT_EMITTED,
            payload={},
            forward_ordinary_tool=False,
        )
