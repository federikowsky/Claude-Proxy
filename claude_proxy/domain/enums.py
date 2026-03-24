from __future__ import annotations

from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class CompatibilityMode(StrEnum):
    TRANSPARENT = "transparent"
    COMPAT = "compat"
    DEBUG = "debug"


class ThinkingPassthroughMode(StrEnum):
    FULL = "full"
    NATIVE_ONLY = "native_only"
    OFF = "off"


class ToolCategory(StrEnum):
    """Deterministic category for a tool definition.

    GENERIC        — generic host tools (Bash, Read, Write, Edit, …):
                     high misuse potential; misuse as control flow must be detected.
    STATE_CONTROL  — Claude Code runtime state/control transition tools
                     (e.g. TodoWrite, exit_plan_mode, …).
    ORCHESTRATION  — subagent / delegation tools (e.g. Task, dispatch_agent, …).
    MCP            — tools following ``mcp__<server>__<tool>`` naming (forwarded; tracked as MCP).
    ORDINARY       — normal domain-specific tool, no special runtime semantics.
    """

    GENERIC = "generic"
    STATE_CONTROL = "state_control"
    ORCHESTRATION = "orchestration"
    MCP = "mcp"
    ORDINARY = "ordinary"


class RuntimeActionType(StrEnum):
    """Canonical classification of a model-emitted tool-use action.

    TOOL_CALL           — ordinary tool call, should be forwarded.
    STATE_TRANSITION    — valid state/control semantic (recognized control tool).
    ORCHESTRATION_ACTION — valid orchestration semantic.
    FINALIZATION_ACTION — completion/end-of-task semantic.
    INVALID_ACTION      — detected misuse or ambiguous action that must be rejected.
    NO_OP               — benign no-op (e.g. explicit empty action), safe to ignore.
    """

    TOOL_CALL = "tool_call"
    STATE_TRANSITION = "state_transition"
    ORCHESTRATION_ACTION = "orchestration_action"
    FINALIZATION_ACTION = "finalization_action"
    INVALID_ACTION = "invalid_action"
    NO_OP = "no_op"


class ActionPolicy(StrEnum):
    """Policy for handling a class of runtime actions in the contract enforcer.

    ALLOW  — pass through without interference.
    WARN   — log a structured warning but allow.
    BLOCK  — reject with a hard error.
    """

    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"
