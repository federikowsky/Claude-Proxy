"""Taxonomy for capability inventory rows (documentation + registry metadata)."""

from __future__ import annotations

from enum import StrEnum


class CapabilityInventoryClass(StrEnum):
    """Freeze inventory sections (maps to docs/runtime/capability-inventory-freeze.md)."""

    BUILTIN_ORDINARY = "builtin_ordinary"
    INTERACTIVE_USER_DECISION = "interactive_user_decision"
    PLAN_MODE_TRANSITION = "plan_mode_transition"
    PERMISSION_APPROVAL_SEMANTICS = "permission_approval_semantics"
    BACKGROUND_EXECUTION = "background_execution"
    SUBAGENT_ORCHESTRATION = "subagent_orchestration"
    MCP_TOOL = "mcp_tool"
    MCP_RESOURCE = "mcp_resource"
    CLI_SESSION_RUNTIME = "cli_session_runtime"
    HOOKS_EVENTS = "hooks_events"
    WORKTREE_REMOTE_TEAM = "worktree_remote_team"
    LEGACY_ALIASES = "legacy_aliases"
    RUNTIME_SYSTEM_MESSAGES = "runtime_system_messages"
    PROVISIONAL_INFERRED = "provisional_inferred"
    SESSION_ABORT = "session_abort"


class EvidenceTier(StrEnum):
    """Provenance strength for a capability row."""

    OFFICIAL_SDK_REFERENCE = "official_sdk_reference"
    OFFICIAL_CLI_DOCUMENTATION = "official_cli_documentation"
    OFFICIAL_HOOKS_DOCUMENTATION = "official_hooks_documentation"
    OFFICIAL_MCP_DOCUMENTATION = "official_mcp_documentation"
    OBSERVED_RUNTIME = "observed_runtime"
    INFERRED_PROVISIONAL = "inferred_provisional"


class SchemaContractKind(StrEnum):
    """Structured input contracts enforced or repaired by the bridge."""

    NONE = "none"
    INTERACTIVE_QUESTION = "interactive_question"
    EXIT_PLAN = "exit_plan"
    TODO_WRITE = "todo_write"
    TODO_READ = "todo_read"
    PERMISSION_REQUEST = "permission_request"
    PLAN_ENTER = "plan_enter"
    ORCHESTRATION_SUBAGENT = "orchestration_subagent"
    BASH_SESSION_ID = "bash_session_id"


class BridgeImplementationStatus(StrEnum):
    """Explicit bridge support level for an inventoried capability (registry row)."""

    IMPLEMENTED = "implemented"
    PARTIAL = "partial"
    INVENTORY_ONLY = "inventory_only"
    EXPLICITLY_OUT_OF_SCOPE = "explicitly_out_of_scope"
    BLOCKED_BY_MISSING_WIRE_CONTRACT = "blocked_by_missing_wire_contract"


class RuntimeFamilyClosureStatus(StrEnum):
    """Closure status for non-tool inventory families (hooks, system messages, …)."""

    IMPLEMENTED = "implemented"
    EXPLICITLY_OUT_OF_SCOPE = "explicitly_out_of_scope"
    INVENTORY_ONLY = "inventory_only"
    BLOCKED_BY_MISSING_WIRE_CONTRACT = "blocked_by_missing_wire_contract"


class TextControlAttemptPolicy(StrEnum):
    """How to handle model plain-text phrases that resemble runtime control language."""

    IGNORE = "ignore"
    WARN = "warn"
    BLOCK = "block"
