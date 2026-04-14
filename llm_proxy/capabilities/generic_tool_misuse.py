"""Deterministic misuse detection for :class:`~ToolCategory.GENERIC` tools (registry bucket).

Bash command-prefix emulation and finalization-shaped input keys are centralized here so
:class:`~RuntimeActionClassifier` does not duplicate policy constants.
"""

from __future__ import annotations

import logging
from typing import Any

from llm_proxy.capabilities.bash_emulation import BASH_CONTROL_EMULATION_PREFIXES
from typing import TYPE_CHECKING

from llm_proxy.domain.enums import RuntimeActionType, ToolCategory
from llm_proxy.domain.models import ToolUseBlock

if TYPE_CHECKING:
    from llm_proxy.application.runtime_actions import RuntimeAction

_logger = logging.getLogger("llm_proxy.runtime")

_FINALIZATION_INPUT_KEYS: frozenset[str] = frozenset({"exit", "done", "finish", "complete"})


def classify_generic_tool_use(block: ToolUseBlock) -> "RuntimeAction":
    """Return :class:`RuntimeAction` for a tool already classified as ``GENERIC``."""
    from llm_proxy.application.runtime_actions import RuntimeAction

    tool_lower = block.name.lower()

    if tool_lower == "bash":
        cmd = _bash_cmd(block.input)
        if cmd is not None:
            cmd_stripped = cmd.strip().lower()
            for prefix in BASH_CONTROL_EMULATION_PREFIXES:
                if cmd_stripped.startswith(prefix):
                    diag = f"bash used as state-control emulation: cmd={cmd!r:.80}"
                    _logger.warning(
                        "runtime_emulation_detected tool=bash cmd=%r",
                        cmd[:80],
                        extra={"extra_fields": {"tool": "bash", "cmd": cmd[:80], "repair": "emulation_detected"}},
                    )
                    return RuntimeAction(
                        action_type=RuntimeActionType.INVALID_ACTION,
                        tool_name=block.name,
                        tool_category=ToolCategory.GENERIC,
                        diagnostic=diag,
                    )

    if isinstance(block.input, dict):
        input_keys = block.input.keys() & _FINALIZATION_INPUT_KEYS
        if input_keys:
            _logger.warning(
                "runtime_emulation_detected tool=%s input_keys=%s",
                block.name,
                ",".join(sorted(input_keys)),
                extra={"extra_fields": {"tool": block.name, "keys": sorted(input_keys)}},
            )
            return RuntimeAction(
                action_type=RuntimeActionType.FINALIZATION_ACTION,
                tool_name=block.name,
                tool_category=ToolCategory.GENERIC,
                diagnostic=f"generic tool with finalization keys: {sorted(input_keys)}",
            )

    return RuntimeAction(
        action_type=RuntimeActionType.TOOL_CALL,
        tool_name=block.name,
        tool_category=ToolCategory.GENERIC,
    )


def _bash_cmd(tool_input: Any) -> str | None:
    if isinstance(tool_input, dict):
        for key in ("command", "cmd", "input", "bash"):
            value = tool_input.get(key)
            if isinstance(value, str):
                return value
    if isinstance(tool_input, str):
        return tool_input
    return None
