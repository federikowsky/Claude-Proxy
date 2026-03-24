"""Canonical runtime action model and classifier.

This module provides the authoritative classification of model-emitted tool-use
blocks into :class:`RuntimeActionType` buckets.

The classifier is the primary enforcement point for the runtime contract.  It
answers the question: *what does this model-emitted tool call actually mean?*

Design
------
* Uses :class:`~claude_proxy.application.tool_classifier.ToolClassifier` for O(1)
  category lookup — no string scanning at classification time.
* ``RuntimeAction`` is a lightweight frozen dataclass carrying the classification
  result together with any diagnostic context.
* ``RuntimeActionClassifier`` is stateless and safe to call concurrently.

Detection logic
---------------
The classifier implements the following logic for a ``ToolUseBlock``:

1. Look up the tool category (via :class:`ToolClassifier`).
2. ``STATE_CONTROL``  → ``STATE_TRANSITION``
3. ``ORCHESTRATION``  → ``ORCHESTRATION_ACTION``
4. ``GENERIC``        → heuristic sub-classification:
   a. If the tool input contains recognisable finalization signals
      (e.g. ``exit``, ``done``) → ``FINALIZATION_ACTION``
   b. Otherwise → ``INVALID_ACTION``  (generic tool used as control emulation)
5. ``ORDINARY``       → ``TOOL_CALL``

The ``GENERIC`` tool sub-classification uses an explicit, small, deterministic
allow-list of input keys rather than free-form string matching.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from claude_proxy.domain.enums import RuntimeActionType, ToolCategory
from claude_proxy.domain.models import ToolUseBlock

_logger = logging.getLogger("claude_proxy.runtime")

# ---------------------------------------------------------------------------
# Input key patterns that indicate finalization intent via a generic tool.
# These are checked only for GENERIC tools so the blast radius is minimal.
# ---------------------------------------------------------------------------
_FINALIZATION_INPUT_KEYS: frozenset[str] = frozenset({"exit", "done", "finish", "complete"})

# ---------------------------------------------------------------------------
# Bash command prefixes that indicate a state-control attempt via Bash.
# Detected to provide a precise diagnostic, not to silently reclassify.
# ---------------------------------------------------------------------------
_BASH_CONTROL_PREFIXES: tuple[str, ...] = (
    "echo done",
    "echo 'done'",
    'echo "done"',
    "echo complete",
    "echo finish",
    "exit 0",
    "exit 1",
)


@dataclass(slots=True, frozen=True)
class RuntimeAction:
    """The classified action produced by :class:`RuntimeActionClassifier`.

    Attributes
    ----------
    action_type:
        Canonical action type.
    tool_name:
        Name of the originating tool call.
    tool_category:
        Category determined for the tool.
    diagnostic:
        Human-readable reason for the classification — important for ``INVALID_ACTION``.
    """

    action_type: RuntimeActionType
    tool_name: str
    tool_category: ToolCategory
    diagnostic: str = ""


class RuntimeActionClassifier:
    """Classify a model-emitted :class:`ToolUseBlock` into a :class:`RuntimeAction`.

    The classifier is stateless and designed to be called once per tool-use block.
    Callers should cache a single instance rather than creating one per call.

    Parameters
    ----------
    tool_classifier:
        A :class:`~claude_proxy.application.tool_classifier.ToolClassifier` instance.
        If not provided, the module-level default is used.
    """

    def __init__(self, tool_classifier=None) -> None:
        from claude_proxy.application.tool_classifier import get_default_classifier

        self._tool_classifier = tool_classifier or get_default_classifier()

    def classify(self, block: ToolUseBlock) -> RuntimeAction:
        """Classify *block* and return a :class:`RuntimeAction`.

        Classification is O(1) in the common path.  The only additional work for
        ``GENERIC`` tools is a small frozenset membership test on input keys.
        """
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

        if category is ToolCategory.GENERIC:
            return self._classify_generic(block)

        # ORDINARY tool → normal tool call
        return RuntimeAction(
            action_type=RuntimeActionType.TOOL_CALL,
            tool_name=block.name,
            tool_category=category,
        )

    def _classify_generic(self, block: ToolUseBlock) -> RuntimeAction:
        """Sub-classify a GENERIC tool use block.

        GENERIC tools being used for legitimate host operations → ``TOOL_CALL``.
        GENERIC tools being (mis)used to signal runtime state changes → ``INVALID_ACTION``.

        The heuristic looks for:
        1. Bash blocks with known finalization command patterns → ``FINALIZATION_ACTION``.
        2. Bash blocks with explicit control-signalling commands → ``INVALID_ACTION``.
        3. Any generic tool with finalization-keyed input fields → ``FINALIZATION_ACTION``.
        4. Otherwise → ``TOOL_CALL`` (legitimate generic host tool call).
        """
        tool_lower = block.name.lower()

        # Bash-specific: check command string for control patterns
        if tool_lower == "bash":
            cmd = self._bash_cmd(block.input)
            if cmd is not None:
                cmd_stripped = cmd.strip().lower()
                # Check finalization intent first (more specific)
                for prefix in _BASH_CONTROL_PREFIXES:
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

        # Generic tool with finalization-keyed input fields
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

        # Normal generic tool call
        return RuntimeAction(
            action_type=RuntimeActionType.TOOL_CALL,
            tool_name=block.name,
            tool_category=ToolCategory.GENERIC,
        )

    @staticmethod
    def _bash_cmd(tool_input: Any) -> str | None:
        """Extract the command string from a Bash tool input, or None if absent."""
        if isinstance(tool_input, dict):
            for key in ("command", "cmd", "input", "bash"):
                value = tool_input.get(key)
                if isinstance(value, str):
                    return value
        if isinstance(tool_input, str):
            return tool_input
        return None
