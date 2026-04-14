# Semantic contract matrix (runtime bridge)

This matrix is the **implementation contract** between:

- capability registry (`llm_proxy/capabilities/`),
- tool / action classification (`application/tool_classifier.py`, `application/runtime_actions.py`, `runtime/classifier.py`),
- input normalization (`capabilities/tool_use_normalize.py`, `capabilities/tool_use_prepare.py`),
- orchestration state machine (`runtime/state_machine.py`),
- persistence / replay (`runtime/recovery.py`, `runtime/persistence/`),
- model-level contract enforcement (`application/runtime_contract.py`),
- YAML policy (`infrastructure/config.py` → `bridge.runtime_policies`, per-model `ActionPolicy` fields).

**Legend**

| Column | Meaning |
|--------|---------|
| Recognized | Primary signals (ordered): registry identity (canonical / alias / MCP pattern) → schema contract kind → category / flags in `CapabilityRecord` → `ToolUseSignalContext` (delivery, origin, session state) for logging and future gates |
| Validated | When invalid shape is rejected vs repaired |
| Normalized | `normalize_tool_use_for_runtime` before `RuntimeModelClassifier` |
| Classified | `RuntimeActionType` + `RuntimeEventKind` |
| Model emits | Tool call from model allowed |
| Runtime emits | Only via control API / host |
| Control API | `/v1/runtime/...` |
| Persisted | Append-only runtime event log |
| Replay | `replay_persisted_session` |
| Forward UI | SSE / JSON response still contains tool block |
| Consumed | Dropped from client-visible content |
| Policy (YAML) | Config key governing behavior |
| Telemetry | Structured log channel |

---

## Matrix (tool-like capabilities)

| Capability id | Recognized | Validated | Normalized | Classified (event) | Model emits | Control API | Persisted | Replay | Forward UI | Consumed | Policy (YAML) | Invalid schema | Semantic misuse | Telemetry |
|---------------|------------|-----------|------------|--------------------|--------------|-------------|-----------|--------|------------|----------|---------------|----------------|-----------------|-----------|
| `interactive_ask_user_question` | Name + `INTERACTIVE_QUESTION` contract | `strict` raises; `repair` coerces; `forward_raw` skips | Yes (`orchestrator`) | `STATE_TRANSITION` → `MODEL_REQUEST_APPROVAL_PROPOSED` | Yes | approve / reject / … | Yes | Yes | No (orchestration path) | Yes | `bridge.runtime_policies.interactive_input_repair` | `RuntimeOrchestrationError` in `strict` | Wrong state → `invalid_runtime_transition` (422) | `llm_proxy.capabilities` repair logs |
| `permission_request_sdk` | Registry | No JSON-schema validator (v1) | No | `MODEL_REQUEST_PERMISSION_PROPOSED` | Yes | grant / deny | Yes | Yes | No | Yes | transition policies `permission_denied` | — | Invalid transition | `http` + domain errors |
| `plan_exit_exit_plan_mode` | Registry + `EXIT_PLAN` contract | `strict` / `repair` | Yes | `MODEL_EXIT_PLAN_PROPOSED` | Yes | — | Yes | Yes | No | Yes | `plan_exit_target` | `RuntimeOrchestrationError` | Invalid transition | repair logs |
| `plan_enter` | Registry | — | No | `MODEL_ENTER_PLAN_PROPOSED` | Yes | — | Yes | Yes | No | Yes | `user_message_from_idle` (idle entry related) | — | — | — |
| `plan_todo_write` | Registry + todo flag | — | No | `MODEL_TEXT_EMITTED` (artifact) | Yes | — | Yes | Yes | No | Yes | — | — | — | `runtime` debug |
| `orchestration_subagent` | Registry | — | No | `MODEL_START_SUBTASK_PROPOSED` | Yes | subtask / … | Yes | Yes | No | Yes | `subtask_failed`, timeouts | — | Subtask policy | — |
| `session_abort_tool` | Registry `triggers_abort` | — | No | `MODEL_ABORT_PROPOSED` | Yes | abort | Yes | Yes | No | Yes | — | — | Terminal rules | — |
| `builtin_*` GENERIC | Registry | `normalize_tool_schema` at request prep | Schema only | `TOOL_CALL` or `FINALIZATION_ACTION` or `INVALID_ACTION` (Bash emulation) | Yes | — | If orchestration on | Yes | Yes / per path | Per path | `generic_tool_emulation_policy` (model) | Provider boundary | Bash / key misuse | `runtime_emulation_detected` |
| MCP pattern | `mcp__…__…` before registry | — | No | `TOOL_CALL` | Yes | — | If orchestration on | Yes | Yes | No | `mcp` implicit ALLOW | — | — | — |

---

## Stream vs non-stream

| Topic | Rule |
|-------|------|
| Classification | Same `RuntimeModelClassifier` + registry |
| Signal context | Stream: `ToolUseSignalContext(delivery="stream", origin="model_tool_use")`; non-stream: default `delivery="non_stream"` (`capabilities/signals.py`) |
| Normalization | Same `normalize_tool_use_for_runtime` in `RuntimeOrchestrator.process_tool_block_start` |
| Forward / consume | Same `ACTION_FORWARDED` / no forward semantics |
| Text-control policy | Same `apply_text_control_policy` on `TextBlock` in `runtime/stream.py` and `application/services.py` |
| Turn boundary | Stream: `log_stream_terminated`; non-stream: `log_upstream_turn_ended` in `MessageService` |

---

## Text-only control attempts

| Signal | State machine effect | Policy (YAML) | Error type (when `block`) |
|--------|---------------------|-----------------|---------------------------|
| Whole-block phrases: “I approve”, “permission granted”, “plan complete”, “done” (normalized) | **None** | `bridge.runtime_policies.text_control_attempt_policy`: `ignore` / `warn` / `block` | `text_control_attempt_blocked` (`TextControlAttemptBlockedError`, HTTP 422) |

Implementation: `llm_proxy/capabilities/text_control.py`. `warn` emits structured JSON on the `llm_proxy.text_control` logger. No transition map involvement.

---

## Executable coverage

- **Code:** `llm_proxy/capabilities/coverage_matrix.py` — `REQUIRED_TESTS_BY_CAPABILITY_ID` must equal the set of registry ids (`validate_test_manifest_matches_registry`).
- **Artifact:** `docs/runtime/capability-coverage.json` — registry rows, MCP pattern row, `non_tool_families` closure (regenerate with `write_coverage_artifact` after registry changes).
- **Tests:** `tests/unit/test_capability_registry.py` (`test_coverage_test_manifest_matches_registry`, `test_exported_coverage_json_registry_ids_match_singleton`).

---

## Typed runtime / contract errors (representative)

| Class | `error_type` | Typical cause |
|-------|--------------|---------------|
| `InvalidToolSchemaContractError` | `invalid_tool_schema_contract` | Strict/repair failure in `normalize_tool_use_for_runtime` |
| `InvalidModelRuntimeActionError` | `invalid_model_runtime_action` | Classifier → invalid model action for bridge |
| `CapabilityNotImplementedInBridgeError` | `capability_not_implemented_in_bridge` | Registry row `implementation_status` = `inventory_only` |
| `InvalidRuntimeTransitionError` | `invalid_runtime_transition` | State machine rejects event |
| `TextControlAttemptBlockedError` | `text_control_attempt_blocked` | Text-control policy `block` |
| `RuntimeInvariantViolationError` | `runtime_invariant_violation` | Invariant checks |
| `RuntimeRecoveryError` | `runtime_recovery_error` | Recovery / replay failure |

All are subclasses of `BridgeError` with stable `error_type` for HTTP/SSE envelopes.

---

## Model `ActionPolicy` mapping (per-model YAML)

| Runtime action | Model setting |
|----------------|---------------|
| `INVALID_ACTION` (generic misuse) | `schema_normalization_policy` + `generic_tool_emulation_policy` |
| `STATE_TRANSITION` | `control_action_policy` |
| `ORCHESTRATION_ACTION` | `orchestration_action_policy` |
| `TOOL_CALL` / `MCP` | Allow path (no extra policy gate in enforcer) |

---

## Persistence roles

| Event kinds | Persisted when orchestration enabled | Replay |
|-------------|--------------------------------------|--------|
| External + model-derived inputs | Yes | `full` / `from_checkpoint` |
| Internal (`STATE_TRANSITION_APPLIED`, …) | Yes (append-only) | Skipped in replay filter (`_INTERNAL_ONLY`) |

---

## Testing obligations (mapping)

| Test module | Covers |
|-------------|--------|
| `tests/unit/test_capability_registry.py` | Registry integrity, MCP pattern, official SDK canonical set, coverage manifest + JSON export |
| `tests/unit/test_text_control.py` | Detection + ignore / warn / block |
| `tests/unit/test_tool_input_normalize.py` | AskUserQuestion / ExitPlanMode repair vs strict |
| `tests/unit/test_runtime_action_classifier.py` | MCP → `TOOL_CALL`, Bash / generic heuristics |
| `tests/unit/runtime/test_classifier.py` | Runtime event mapping |
| `tests/integration/test_runtime_e2e_flows.py` | End-to-end tool → control API; text-control block (stream + non-stream) |
| `tests/integration/test_runtime_control_http.py` | Control plane + SQLite |

---

## Change control

1. Update `builtins.py` + `REQUIRED_TESTS_BY_CAPABILITY_ID` in `coverage_matrix.py` + regenerate `docs/runtime/capability-coverage.json`.
2. Add/adjust tests in the rows above.
3. If YAML surface changes, update `infrastructure/config.py` + `policy_binding.py` + sample `config/llm-proxy.yaml`.
