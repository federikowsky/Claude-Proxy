"""Canonical runtime action model and classifier (registry + capability misuse modules)."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from claude_proxy.capabilities.generic_tool_misuse import classify_generic_tool_use
from claude_proxy.capabilities.ordinary_tool_emulation import classify_ordinary_with_control_emulation
from claude_proxy.domain.enums import RuntimeActionType, ToolCategory
from claude_proxy.domain.models import ToolUseBlock

_logger = logging.getLogger("claude_proxy.runtime")


@dataclass(slots=True, frozen=True)
class RuntimeAction:
    action_type: RuntimeActionType
    tool_name: str
    tool_category: ToolCategory
    diagnostic: str = ""


class RuntimeActionClassifier:
    """Classify a model-emitted :class:`ToolUseBlock` using :class:`ToolClassifier` + misuse modules."""

    def __init__(self, tool_classifier=None) -> None:
        from claude_proxy.application.tool_classifier import get_default_classifier

        self._tool_classifier = tool_classifier or get_default_classifier()

    def classify(self, block: ToolUseBlock) -> RuntimeAction:
        category = self._tool_classifier.classify_by_name(block.name)

        if category is ToolCategory.STATE_CONTROL:
            action = RuntimeAction(
                action_type=RuntimeActionType.STATE_TRANSITION,
                tool_name=block.name,
                tool_category=category,
                diagnostic=f"recognized state/control tool: {block.name}",
            )
            _logger.debug(
                "runtime_action tool=%s action=%s",
                block.name,
                action.action_type,
                extra={"extra_fields": {"tool": block.name, "action": action.action_type}},
            )
            return action

        if category is ToolCategory.ORCHESTRATION:
            action = RuntimeAction(
                action_type=RuntimeActionType.ORCHESTRATION_ACTION,
                tool_name=block.name,
                tool_category=category,
                diagnostic=f"recognized orchestration tool: {block.name}",
            )
            _logger.debug(
                "runtime_action tool=%s action=%s",
                block.name,
                action.action_type,
                extra={"extra_fields": {"tool": block.name, "action": action.action_type}},
            )
            return action

        if category is ToolCategory.MCP:
            return RuntimeAction(
                action_type=RuntimeActionType.TOOL_CALL,
                tool_name=block.name,
                tool_category=category,
                diagnostic="mcp_style_tool_forward",
            )

        if category is ToolCategory.GENERIC:
            return classify_generic_tool_use(block)

        suspicious = classify_ordinary_with_control_emulation(block)
        if suspicious is not None:
            return suspicious

        return RuntimeAction(
            action_type=RuntimeActionType.TOOL_CALL,
            tool_name=block.name,
            tool_category=category,
        )
