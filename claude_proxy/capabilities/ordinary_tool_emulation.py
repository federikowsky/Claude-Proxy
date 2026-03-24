"""Detect control-shaped payloads on :class:`~ToolCategory.ORDINARY` tools (non-registry host tools)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from claude_proxy.domain.enums import RuntimeActionType, ToolCategory
from claude_proxy.domain.models import ToolUseBlock

if TYPE_CHECKING:
    from claude_proxy.application.runtime_actions import RuntimeAction

# Top-level keys that resemble Claude Code / SDK control payloads, not domain data.
_SUSPICIOUS_CONTROL_KEYS: frozenset[str] = frozenset(
    {
        "approved",
        "user_approved",
        "permission_granted",
        "plan_approved",
        "exit_plan",
    },
)


def classify_ordinary_with_control_emulation(block: ToolUseBlock) -> "RuntimeAction | None":
    """Return ``INVALID_ACTION`` if *block* looks like control emulation; else ``None``."""
    from claude_proxy.application.runtime_actions import RuntimeAction

    if not isinstance(block.input, dict):
        return None
    overlap = block.input.keys() & _SUSPICIOUS_CONTROL_KEYS
    if not overlap:
        return None
    return RuntimeAction(
        action_type=RuntimeActionType.INVALID_ACTION,
        tool_name=block.name,
        tool_category=ToolCategory.ORDINARY,
        diagnostic=f"ordinary tool with control-shaped keys: {sorted(overlap)}",
    )
