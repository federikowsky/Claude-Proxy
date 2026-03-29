"""Frozen built-in capability rows — keep in sync with docs/runtime/capability-inventory-freeze.md."""

from __future__ import annotations

from claude_proxy.capabilities.enums import (
    BridgeImplementationStatus,
    CapabilityInventoryClass,
    EvidenceTier,
    SchemaContractKind,
)
from claude_proxy.capabilities.record import CapabilityRecord
from claude_proxy.domain.enums import ToolCategory

_I = CapabilityInventoryClass
_E = EvidenceTier
_TC = ToolCategory
_S = SchemaContractKind
_B = BridgeImplementationStatus

_PARTIAL_FORWARD_ONLY = (
    "Proxy forwards the tool call only; no host execution, output validation, or "
    "side-effect checks are performed inside the bridge."
)


def builtin_capability_records() -> tuple[CapabilityRecord, ...]:
    return (
        # --- Interactive / user decision (SDK AskUserQuestion contract) ---
        CapabilityRecord(
            id="interactive_ask_user_question",
            canonical_name="AskUserQuestion",
            aliases=frozenset({"askuserquestion", "ask_user", "approval"}),
            inventory_class=_I.INTERACTIVE_USER_DECISION,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.STATE_CONTROL,
            runtime_event_value="model_request_approval_proposed",
            schema_contract=_S.INTERACTIVE_QUESTION,
        ),
        CapabilityRecord(
            id="permission_request_sdk",
            canonical_name="request_permissions",
            aliases=frozenset({"permission_request", "request_permission"}),
            inventory_class=_I.PERMISSION_APPROVAL_SEMANTICS,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.STATE_CONTROL,
            runtime_event_value="model_request_permission_proposed",
            schema_contract=_S.PERMISSION_REQUEST,
        ),
        # --- Plan mode ---
        CapabilityRecord(
            id="plan_exit_exit_plan_mode",
            canonical_name="ExitPlanMode",
            aliases=frozenset({"exit_plan_mode"}),
            inventory_class=_I.PLAN_MODE_TRANSITION,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.STATE_CONTROL,
            runtime_event_value="model_exit_plan_proposed",
            schema_contract=_S.EXIT_PLAN,
        ),
        CapabilityRecord(
            id="plan_enter",
            canonical_name="enter_plan_mode",
            aliases=frozenset({"enter_plan_mode", "plan_mode"}),
            inventory_class=_I.PLAN_MODE_TRANSITION,
            evidence_tier=_E.OBSERVED_RUNTIME,
            tool_category=_TC.STATE_CONTROL,
            runtime_event_value="model_enter_plan_proposed",
            schema_contract=_S.PLAN_ENTER,
        ),
        CapabilityRecord(
            id="plan_todo_write",
            canonical_name="TodoWrite",
            aliases=frozenset({"todowrite"}),
            inventory_class=_I.PLAN_MODE_TRANSITION,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.STATE_CONTROL,
            todo_write_text_signal=True,
            schema_contract=_S.TODO_WRITE,
        ),
        CapabilityRecord(
            id="builtin_todo_read",
            canonical_name="TodoRead",
            aliases=frozenset({"todoread"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
            schema_contract=_S.TODO_READ,
        ),
        # --- Subagent / orchestration (Agent + legacy Task + aliases) ---
        CapabilityRecord(
            id="orchestration_subagent",
            canonical_name="Agent",
            aliases=frozenset({"agent", "task", "dispatch_agent", "invoke_subagent", "delegate"}),
            inventory_class=_I.SUBAGENT_ORCHESTRATION,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.ORCHESTRATION,
            schema_contract=_S.ORCHESTRATION_SUBAGENT,
        ),
        # --- Session abort (model-emitted) ---
        CapabilityRecord(
            id="session_abort_tool",
            canonical_name="abort",
            aliases=frozenset(
                {
                    "abort_session",
                    "session_abort",
                    "end_session",
                    "kill_session",
                    "cancel_session",
                },
            ),
            inventory_class=_I.SESSION_ABORT,
            evidence_tier=_E.OBSERVED_RUNTIME,
            tool_category=_TC.STATE_CONTROL,
            triggers_abort=True,
        ),
        # --- Host / ordinary built-ins (generic bucket for emulation heuristics) ---
        CapabilityRecord(
            id="builtin_bash",
            canonical_name="Bash",
            aliases=frozenset({"bash"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_computer",
            canonical_name="computer",
            aliases=frozenset({"computer"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.INFERRED_PROVISIONAL,
            tool_category=_TC.GENERIC,
            implementation_status=_B.PARTIAL,
            residual_limitation=_PARTIAL_FORWARD_ONLY,
        ),
        CapabilityRecord(
            id="builtin_read",
            canonical_name="Read",
            aliases=frozenset({"read"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_write",
            canonical_name="Write",
            aliases=frozenset({"write"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_edit",
            canonical_name="Edit",
            aliases=frozenset({"edit", "multiedit"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_glob",
            canonical_name="Glob",
            aliases=frozenset({"glob"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_grep",
            canonical_name="Grep",
            aliases=frozenset({"grep"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_ls",
            canonical_name="ls",
            aliases=frozenset({"ls"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_notebook",
            canonical_name="NotebookEdit",
            aliases=frozenset({"notebookedit", "notebookread"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_webfetch",
            canonical_name="WebFetch",
            aliases=frozenset({"webfetch", "webbrowser"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="builtin_websearch",
            canonical_name="WebSearch",
            aliases=frozenset({"websearch"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.INFERRED_PROVISIONAL,
            tool_category=_TC.GENERIC,
            implementation_status=_B.PARTIAL,
            residual_limitation=_PARTIAL_FORWARD_ONLY,
        ),
        CapabilityRecord(
            id="builtin_screenshot",
            canonical_name="screenshottool",
            aliases=frozenset({"screenshottool"}),
            inventory_class=_I.BUILTIN_ORDINARY,
            evidence_tier=_E.INFERRED_PROVISIONAL,
            tool_category=_TC.GENERIC,
            implementation_status=_B.PARTIAL,
            residual_limitation=_PARTIAL_FORWARD_ONLY,
        ),
        # --- Background execution ---
        CapabilityRecord(
            id="builtin_bash_output",
            canonical_name="BashOutput",
            aliases=frozenset({"bashoutput"}),
            inventory_class=_I.BACKGROUND_EXECUTION,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
            schema_contract=_S.BASH_SESSION_ID,
        ),
        CapabilityRecord(
            id="builtin_kill_bash",
            canonical_name="KillBash",
            aliases=frozenset({"killbash"}),
            inventory_class=_I.BACKGROUND_EXECUTION,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
            schema_contract=_S.BASH_SESSION_ID,
        ),
        # --- MCP resource helpers (named tools, not mcp__ pattern) ---
        CapabilityRecord(
            id="mcp_list_resources",
            canonical_name="ListMcpResources",
            aliases=frozenset({"listmcpresources"}),
            inventory_class=_I.MCP_RESOURCE,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        CapabilityRecord(
            id="mcp_read_resource",
            canonical_name="ReadMcpResource",
            aliases=frozenset({"readmcpresource"}),
            inventory_class=_I.MCP_RESOURCE,
            evidence_tier=_E.OFFICIAL_SDK_REFERENCE,
            tool_category=_TC.GENERIC,
        ),
        # --- Forwarded host/session helpers (no orchestration event) ---
        CapabilityRecord(
            id="host_record_thinking",
            canonical_name="record_thinking",
            aliases=frozenset({"record_thinking"}),
            inventory_class=_I.CLI_SESSION_RUNTIME,
            evidence_tier=_E.OBSERVED_RUNTIME,
            tool_category=_TC.ORDINARY,
        ),
        CapabilityRecord(
            id="host_set_env",
            canonical_name="set_env",
            aliases=frozenset({"set_env"}),
            inventory_class=_I.CLI_SESSION_RUNTIME,
            evidence_tier=_E.OBSERVED_RUNTIME,
            tool_category=_TC.ORDINARY,
        ),
        CapabilityRecord(
            id="host_clear_env",
            canonical_name="clear_env",
            aliases=frozenset({"clear_env"}),
            inventory_class=_I.CLI_SESSION_RUNTIME,
            evidence_tier=_E.OBSERVED_RUNTIME,
            tool_category=_TC.ORDINARY,
        ),
    )


OFFICIAL_SDK_TOOL_CANONICALS: frozenset[str] = frozenset(
    {
        "Agent",
        "AskUserQuestion",
        "Bash",
        "Edit",
        "Read",
        "Write",
        "Glob",
        "Grep",
        "NotebookEdit",
        "WebFetch",
        "WebSearch",
        "TodoWrite",
        "BashOutput",
        "KillBash",
        "ExitPlanMode",
        "ListMcpResources",
        "ReadMcpResource",
    },
)
