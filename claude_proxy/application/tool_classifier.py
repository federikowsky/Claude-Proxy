"""Tool classification layer.

Provides a deterministic, O(1) classification of tool definitions into canonical
:class:`~claude_proxy.domain.enums.ToolCategory` buckets.

Classification is table-driven: the authoritative sets are frozensets computed once
at module load time.  No regex passes, no per-call string scanning in hot paths.

The classifier is a thin stateless service; callers hold a reference and reuse it.

Design notes
------------
* ``GENERIC_TOOLS`` — well-known Claude Code host-provided generic tools that have
  high misuse potential (e.g. Bash for state control).  Membership is checked first
  because misuse detection depends on this distinction.
* ``STATE_CONTROL_TOOLS`` — Claude Code runtime state/control tools.  A model that
  correctly emits these is making a valid state transition.
* ``ORCHESTRATION_TOOLS`` — subagent / delegation tools.
* Everything else → ``ORDINARY``.
"""

from __future__ import annotations

from claude_proxy.domain.enums import ToolCategory
from claude_proxy.domain.models import ToolDefinition

# ---------------------------------------------------------------------------
# Canonical tool name sets — all lowercase for case-insensitive lookup.
# ---------------------------------------------------------------------------

# Well-known Claude Code generic host tools.  These are legitimate tools but their
# misuse as runtime-control emulation is the primary detection target.
GENERIC_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "bash",
        "computer",
        "read",
        "write",
        "edit",
        "multiedit",
        "glob",
        "grep",
        "ls",
        "notebookread",
        "notebookedit",
        "webbrowser",
        "webfetch",
        "screenshottool",
    }
)

# Claude Code runtime state/control tools.  Emitting one of these represents a
# valid (intended) state transition, not a misuse.
STATE_CONTROL_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "todowrite",
        "todoread",
        "exit_plan_mode",
        "request_permissions",
        "permission_request",
        "request_permission",
        "ask_user",
        "approval",
        "record_thinking",
        "set_env",
        "clear_env",
    }
)

# Claude Code orchestration/delegation tools.
ORCHESTRATION_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "task",
        "dispatch_agent",
        "invoke_subagent",
        "delegate",
    }
)


class ToolClassifier:
    """Classify :class:`ToolDefinition` objects into canonical :class:`ToolCategory` buckets.

    Lookup is O(1) via frozenset membership tests.  The classifier is stateless and
    safe to call from multiple coroutines concurrently.
    """

    def classify(self, tool: ToolDefinition) -> ToolCategory:
        """Return the :class:`ToolCategory` for *tool*.

        Classification is deterministic and based solely on the normalised tool name.
        Unknown names fall through to :attr:`~ToolCategory.ORDINARY`.
        """
        name_lower = tool.name.lower()
        if name_lower in STATE_CONTROL_TOOL_NAMES:
            return ToolCategory.STATE_CONTROL
        if name_lower in ORCHESTRATION_TOOL_NAMES:
            return ToolCategory.ORCHESTRATION
        if name_lower in GENERIC_TOOL_NAMES:
            return ToolCategory.GENERIC
        return ToolCategory.ORDINARY

    def classify_by_name(self, name: str) -> ToolCategory:
        """Classify by raw tool name string — avoids a ``ToolDefinition`` allocation."""
        name_lower = name.lower()
        if name_lower in STATE_CONTROL_TOOL_NAMES:
            return ToolCategory.STATE_CONTROL
        if name_lower in ORCHESTRATION_TOOL_NAMES:
            return ToolCategory.ORCHESTRATION
        if name_lower in GENERIC_TOOL_NAMES:
            return ToolCategory.GENERIC
        return ToolCategory.ORDINARY

    def annotate(self, tool: ToolDefinition) -> ToolDefinition:
        """Return a *new* :class:`ToolDefinition` with :attr:`~ToolDefinition.category` set.

        If the tool already has the correct category, the original object is returned
        unchanged (identity preserved, no allocation).
        """
        category = self.classify(tool)
        if tool.category is category:
            return tool
        from dataclasses import replace

        return replace(tool, category=category)

    def annotate_all(
        self, tools: tuple[ToolDefinition, ...]
    ) -> tuple[ToolDefinition, ...]:
        """Annotate a sequence of tools; return the original tuple if no changes are needed."""
        annotated = tuple(self.annotate(t) for t in tools)
        # Preserve identity when all tools were already correctly categorised.
        if all(a is b for a, b in zip(annotated, tools)):
            return tools
        return annotated


# Module-level singleton — importers may use this directly.
_default_classifier = ToolClassifier()


def get_default_classifier() -> ToolClassifier:
    """Return the module-level default :class:`ToolClassifier` instance."""
    return _default_classifier
