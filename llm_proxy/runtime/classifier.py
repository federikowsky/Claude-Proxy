"""Map model artifacts to normalized actions and runtime event kinds (registry-driven)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from llm_proxy.application.runtime_actions import RuntimeActionClassifier
from llm_proxy.capabilities.registry import get_capability_registry
from llm_proxy.capabilities.signals import ToolUseSignalContext
from llm_proxy.domain.enums import RuntimeActionType
from llm_proxy.domain.models import TextBlock, ToolUseBlock
from llm_proxy.runtime.actions import NormalizedRuntimeAction
from llm_proxy.runtime.events import RuntimeEventKind

_logger = logging.getLogger("llm_proxy.runtime.classifier")


def _log_multisignal(block: ToolUseBlock, ctx: ToolUseSignalContext | None) -> None:
    if ctx is None:
        return
    _logger.debug(
        "model_tool_classify context=%s",
        {
            "tool": block.name,
            "delivery": ctx.delivery,
            "origin": ctx.origin,
            "session_state": ctx.session_state,
        },
    )


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

    def classify_tool_use(
        self,
        block: ToolUseBlock,
        *,
        signal_context: ToolUseSignalContext | None = None,
    ) -> ModelClassification:
        _log_multisignal(block, signal_context)
        reg = get_capability_registry()
        name_lower = block.name.lower()
        payload: dict[str, Any] = {
            "tool_use_id": block.id,
            "tool_name": block.name,
            "input": block.input,
        }

        if reg.triggers_abort(name_lower):
            return ModelClassification(
                normalized=NormalizedRuntimeAction.ABORT_ACTION,
                event_kind=RuntimeEventKind.MODEL_ABORT_PROPOSED,
                payload=payload,
                forward_ordinary_tool=False,
            )

        if reg.todo_write_text_signal(name_lower):
            return ModelClassification(
                normalized=NormalizedRuntimeAction.STATE_TRANSITION_ACTION,
                event_kind=RuntimeEventKind.MODEL_TEXT_EMITTED,
                payload={"tool_name": block.name, "kind": "todo_write"},
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
            ev = reg.control_runtime_event(name_lower)
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
