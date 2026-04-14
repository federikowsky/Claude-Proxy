# Runtime capability inventory (freeze)

**Status:** freeze-ready specification aligned with code in `llm_proxy/capabilities/`.  
**Audience:** implementers of the proxy runtime bridge, contract tests, and operators.  
**Evidence tiers:** `official_sdk_reference` · `official_cli_documentation` · `official_hooks_documentation` · `official_mcp_documentation` · `observed_runtime` · `inferred_provisional`.

Rows marked **provisional** are structured for forward-compat and must not be treated as Anthropic guarantees.

---

## 1. Built-in ordinary tools

| Canonical name | Aliases (lowercase) | Source | Input / output (summary) | Execution domain | Bridge handling |
|----------------|---------------------|--------|--------------------------|------------------|-----------------|
| Bash | `bash` | SDK reference | Shell command / output | Host execution | `ToolCategory.GENERIC`; emulation patterns → `INVALID_ACTION` |
| Read | `read` | SDK reference | Paths / limits | Host execution | Forward; finalization keys on input → `FINALIZATION_ACTION` |
| Write | `write` | SDK reference | Path / content | Host execution | Forward |
| Edit | `edit`, `multiedit` | SDK reference | Edit operations | Host execution | Forward |
| Glob | `glob` | SDK reference | Pattern search | Host execution | Forward |
| Grep | `grep` | SDK reference | Search | Host execution | Forward |
| ls | `ls` | observed_runtime | Directory listing | Host execution | Forward |
| computer | `computer` | inferred_provisional | Desktop / UI automation | Host execution | Forward |
| NotebookEdit | `notebookedit`, `notebookread` | SDK reference | Notebook cells | Host execution | Forward |
| WebFetch | `webfetch`, `webbrowser` | SDK reference | URL fetch | External I/O | Forward |
| WebSearch | `websearch` | inferred_provisional | Web search | External I/O | Forward |
| screenshottool | `screenshottool` | inferred_provisional | Screenshot | Host execution | Forward |

---

## 2. Interactive / user-decision tools

| Canonical | Aliases | Source | Contract | Bridge handling |
|-----------|---------|--------|----------|-----------------|
| AskUserQuestion | `askuserquestion`, `ask_user`, `approval` | SDK reference + observed | `questions[]` (1–4), each with `question`, `header`, `options` (2–4), `multiSelect`; optional `answers` | `SchemaContractKind.INTERACTIVE_QUESTION`; `bridge.runtime_policies.interactive_input_repair` (`repair` / `forward_raw` / `strict`); orchestration → `MODEL_REQUEST_APPROVAL_PROPOSED` |

---

## 3. Plan / mode transition tools

| Canonical | Aliases | Source | Contract | Bridge handling |
|-----------|---------|--------|----------|-----------------|
| ExitPlanMode | `exit_plan_mode` | SDK reference | `plan: str`; output `approved` | `SchemaContractKind.EXIT_PLAN` + repair/strict; → `MODEL_EXIT_PLAN_PROPOSED` |
| enter_plan_mode | `enter_plan_mode`, `plan_mode` | observed_runtime | Implementation-defined | → `MODEL_ENTER_PLAN_PROPOSED` |
| TodoWrite | `todowrite` | SDK reference | Todos structure | Consumed as planning signal → `MODEL_TEXT_EMITTED` (not forwarded as tool call) |
| TodoRead | `todoread` | SDK reference | Read todos | `ToolCategory.GENERIC` → ordinary forward |

---

## 4. Permission / approval semantics

| Canonical | Aliases | Source | Bridge handling |
|-----------|---------|--------|-----------------|
| request_permissions | `request_permissions` | SDK reference | → `MODEL_REQUEST_PERMISSION_PROPOSED` |
| (alias surface) | `permission_request`, `request_permission` | observed_runtime | Same event mapping |

CLI concepts (`--permission-mode`, `default` / `acceptEdits` / `plan` / `bypassPermissions`) are **session/host** semantics: documented here for inventory completeness; they are **not** modeled as tool names in the registry.

---

## 5. Background execution tools

| Canonical | Aliases | Source | Bridge handling |
|-----------|---------|--------|-----------------|
| BashOutput | `bashoutput` | SDK reference | Forward as `GENERIC` tool call |
| KillBash | `killbash` | SDK reference | Forward as `GENERIC` tool call |

---

## 6. Subagent / orchestration tools

| Canonical | Aliases | Source | Bridge handling |
|-----------|---------|--------|-----------------|
| Agent | `agent`, `task`, `dispatch_agent`, `invoke_subagent`, `delegate` | SDK reference (`Task` legacy) | → `ORCHESTRATION_ACTION` / `MODEL_START_SUBTASK_PROPOSED` |

Runtime/UI messages such as `TaskStartedMessage`, `TaskProgressMessage`, and hook events `SubagentStart` / `SubagentStop` are **not** tool calls: they belong to hooks/system-message inventory (§12–13) and may be extended when wire format is stable in this proxy.

---

## 7. MCP tools

| Pattern | Source | Bridge handling |
|---------|--------|-----------------|
| `mcp__<server>__<tool>` (tool segment may contain additional `__`) | MCP + Agent SDK naming docs | `ToolCategory.MCP` → `RuntimeActionType.TOOL_CALL` (forward) |

---

## 8. MCP resources (named bridge tools)

| Canonical | Aliases | Source | Bridge handling |
|-----------|---------|--------|-----------------|
| ListMcpResources | `listmcpresources` | SDK reference | Forward (`GENERIC`) |
| ReadMcpResource | `readmcpresource` | SDK reference | Forward (`GENERIC`) |

---

## 9. CLI / session runtime (selected)

Documented CLI flags (non-tool): `--session-id`, `--worktree`, `--teammate-mode`, `--remote`, `--remote-control`, `--system-prompt*`, `--tools`, `--permission-prompt-tool`. These inform **session** metadata and policies but are **not** classified via tool name in the current code path.

Registry tools for host helpers:

| Canonical | Aliases | Tier | Bridge |
|-----------|---------|------|--------|
| record_thinking | `record_thinking` | observed | `ORDINARY` forward |
| set_env | `set_env` | observed | `ORDINARY` forward |
| clear_env | `clear_env` | observed | `ORDINARY` forward |

---

## 10. Non-tool families (formal closure)

Authoritative tuple: `llm_proxy/capabilities/families.py` → `NON_TOOL_FAMILY_CLOSURE`.  
Executable export: `docs/runtime/capability-coverage.json` → `non_tool_families`.

| Family | Status | Rationale (summary) |
|--------|--------|---------------------|
| `hooks` | `blocked_by_missing_wire_contract` | Hook events need a normalized event stream in the proxy; not present. |
| `runtime_system_messages` | `blocked_by_missing_wire_contract` | Task/progress wire shapes are not canonical runtime events in this repo. |
| `worktree` | `explicitly_out_of_scope` | Host/CLI concerns; no stable proxy API here. |
| `remote` | `explicitly_out_of_scope` | Remote flags are session/CLI config, not translated through this HTTP bridge. |
| `teammate` | `explicitly_out_of_scope` | Product surface without a dedicated proxy protocol in this repo. |
| `background_task_progress` | `inventory_only` | Documented for parity; ordinary tool forward + orchestration apply where tools exist. |

---

## 11. Hooks / worktree / remote / teammate (reference)

Examples from hooks documentation: `PreToolUse`, `PostToolUse`, `PostToolUseFailure`, `PermissionRequest`, `UserPromptSubmit`, `Stop`, `SubagentStart`, `SubagentStop`, `TaskCompleted`, `WorktreeCreate`, `WorktreeRemove`.  
**Binding status:** see §10; do not treat these as implicit `CapabilityRecord` rows.

---

## 12. Legacy aliases / backward compatibility

Covered above: `Task`→`Agent`, `ask_user`→`AskUserQuestion`, `plan_mode`→`enter_plan_mode`, permission alias cluster.

---

## 13. Runtime-only / system messages

Task progress / background task classes from SDK docs are listed in §6 note.  
**Text-only control phrases** (e.g. “I approve”, “done”, “plan complete”, “permission granted”) **never** apply `RuntimeEventKind` transitions. They are handled only by `llm_proxy/capabilities/text_control.py` with YAML `bridge.runtime_policies.text_control_attempt_policy` (`ignore` / `warn` / `block`).

---

## 14. Provisional / inferred capabilities

| Item | Tier | Notes |
|------|------|--------|
| WebSearch | inferred_provisional | Listed like other host tools until SDK row is pinned |
| computer / screenshottool | inferred_provisional | Common Claude Code surfaces |

---

## Code anchor

- Descriptor table: `llm_proxy/capabilities/builtins.py` → `builtin_capability_records()`
- Resolver: `llm_proxy/capabilities/registry.py` → `get_capability_registry()`
- Coverage manifest + export: `llm_proxy/capabilities/coverage_matrix.py` → `REQUIRED_TESTS_BY_CAPABILITY_ID`, `export_coverage_json_bytes()`, `write_coverage_artifact()`
- Generated artifact: `docs/runtime/capability-coverage.json`
- Text-control policy: `llm_proxy/capabilities/text_control.py`, `llm_proxy/infrastructure/config.py` → `RuntimeOrchestrationPolicySettings.text_control_attempt_policy`
