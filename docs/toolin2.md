# Claude-Proxy — Runtime Orchestration System Specification
**Status:** Freeze-ready  
**Scope:** Full production runtime orchestration for Claude Code compatibility over non-Claude models  
**Supersedes:** all previous partial/runtime-contract-only designs  
**Non-goals:** MVP, demo, reduced-state runtime, heuristic-only guard layer

---

## 1. Objective

This system defines the **full runtime orchestration layer** required to make Claude Code operate credibly over non-Claude models through `claude-proxy`, without relying on native Claude runtime semantics.

The proxy is no longer only a transport normalizer and contract guard. It becomes a **deterministic runtime control plane** that:

- interprets runtime-control outputs emitted by the model,
- owns session state,
- enforces valid state transitions,
- mediates permissions and approvals,
- orchestrates delegated/sub-agent work,
- preserves streaming semantics,
- provides deterministic recovery and replay,
- separates ordinary tool execution from runtime control semantics.

The proxy must remain:

- deterministic in control flow,
- explicit in state ownership,
- auditable,
- recoverable,
- low-overhead,
- modular,
- safe under malformed or drifting model behavior.

---

## 2. Core Principles

## 2.1 Architectural principles

The runtime must follow these invariants:

1. **Runtime state is authoritative in the proxy, never in the model.**
2. **The model may propose runtime actions; it does not own them.**
3. **Ordinary tool calls and runtime-control actions are different classes of output.**
4. **Every state transition must be explicit, validated, and recorded.**
5. **Streaming must not bypass orchestration.**
6. **The runtime must be recoverable from persisted event history.**
7. **Invalid transitions must fail deterministically.**
8. **No hidden implicit state changes.**
9. **No dependence on “Claude probably meant X”.**
10. **Heuristics may assist classification, but execution must depend on validated runtime semantics.**

## 2.2 Operational principles

The system must support:

- long-lived sessions,
- interleaved planning and execution,
- approval-gated steps,
- permission-gated steps,
- delegated task orchestration,
- resumable interrupted runs,
- deterministic completion/finalization,
- robust handling of upstream model drift.

---

## 3. Runtime responsibility split

## 3.1 Model responsibilities

The model may:

- produce text,
- produce ordinary tool calls,
- emit runtime-control proposals,
- emit completion/finalization proposals,
- emit delegation proposals.

The model may **not**:

- directly mutate runtime state,
- directly enter/exit modes,
- directly mark tasks approved,
- directly grant itself permissions,
- directly finalize a session,
- directly declare orchestration side-effects as committed.

## 3.2 Runtime responsibilities

The runtime must:

- classify model outputs,
- validate action applicability against current state,
- consume runtime-control actions internally,
- emit ordinary tool calls to the client only when valid,
- block or reject illegal runtime actions,
- persist state transitions,
- manage delegated task state,
- provide approval/permission waiting states,
- synthesize deterministic error outputs when runtime rules are violated.

---

## 4. Domain model

## 4.1 Session

A **Session** is the top-level runtime boundary for a Claude Code conversation routed through the proxy.

A session owns:

- session id,
- current runtime state,
- current mode stack / mode flags,
- approval status,
- permission status,
- active delegated tasks,
- current execution turn state,
- runtime event log,
- resumable checkpoints,
- metadata required for recovery.

## 4.2 Turn

A **Turn** is one user-triggered or runtime-triggered unit of progression through the system.

A turn has:

- turn id,
- triggering event,
- state before turn,
- state after turn,
- emitted outputs,
- persisted runtime events,
- execution result.

## 4.3 Runtime action

A **RuntimeAction** is an internally normalized interpretation of model output or external input.

Examples:

- enter plan mode,
- exit plan mode,
- request approval,
- approval granted,
- approval denied,
- request permission,
- permission granted,
- permission denied,
- start delegated task,
- delegated task completed,
- delegated task failed,
- mark execution complete,
- abort run,
- resume run.

## 4.4 Ordinary tool action

An **OrdinaryToolAction** is a normal tool invocation that is not itself a runtime-control operation.

Examples:

- bash,
- read,
- write,
- edit,
- grep,
- glob,
- ls,
- web fetch/search,
- any external domain tool.

---

## 5. Runtime state model

The runtime must implement the full state machine below.

## 5.1 Top-level states

1. `IDLE`
2. `PLANNING`
3. `AWAITING_APPROVAL`
4. `AWAITING_PERMISSION`
5. `EXECUTING`
6. `EXECUTING_TOOL`
7. `ORCHESTRATING`
8. `AWAITING_SUBTASK`
9. `PAUSED`
10. `COMPLETING`
11. `COMPLETED`
12. `FAILED`
13. `ABORTED`
14. `INTERRUPTED`
15. `RECOVERING`

These are runtime-authoritative states. No hidden shadow states are allowed.

## 5.2 State meanings

### `IDLE`
No active execution is in progress. Session is ready for new user-triggered work.

### `PLANNING`
The runtime is in planning mode. Model may produce planning text and runtime proposals, but execution side effects are not yet committed.

### `AWAITING_APPROVAL`
Runtime is blocked until a user or external controller explicitly approves or rejects the gated action or plan.

### `AWAITING_PERMISSION`
Runtime is blocked until an execution permission decision is provided.

### `EXECUTING`
Execution is active. The model may emit ordinary tool calls and runtime orchestration proposals allowed in execution context.

### `EXECUTING_TOOL`
A concrete tool action has been issued and is in-flight.

### `ORCHESTRATING`
Runtime is managing higher-order task coordination such as delegation, subtask scheduling, or task lifecycle control.

### `AWAITING_SUBTASK`
The runtime is blocked on the result of one or more delegated subtasks.

### `PAUSED`
Execution is intentionally paused but not failed or completed.

### `COMPLETING`
The runtime has entered finalization. No new ordinary execution work should start unless completion is rolled back.

### `COMPLETED`
The session turn has ended successfully.

### `FAILED`
The turn failed due to runtime, tool, or validation failure.

### `ABORTED`
Execution was intentionally terminated.

### `INTERRUPTED`
Execution was externally interrupted or broken mid-stream / mid-execution but remains potentially recoverable.

### `RECOVERING`
Runtime is replaying or restoring session state from persisted events or a checkpoint.

---

## 6. Mode model

Modes are not separate from state; they are runtime qualifiers. They must still be explicit and persisted.

Supported modes:

- `plan_mode`
- `approval_mode`
- `permission_mode`
- `execution_mode`
- `delegation_mode`
- `completion_mode`

Mode invariants:

- `plan_mode` may coexist only with `PLANNING`
- `approval_mode` may coexist only with `AWAITING_APPROVAL`
- `permission_mode` may coexist only with `AWAITING_PERMISSION`
- `execution_mode` may coexist with `EXECUTING`, `EXECUTING_TOOL`, `ORCHESTRATING`, `AWAITING_SUBTASK`
- `delegation_mode` may coexist with `ORCHESTRATING` or `AWAITING_SUBTASK`
- `completion_mode` may coexist only with `COMPLETING`

Mode flags must never be inferred from raw text alone once runtime state exists.

---

## 7. Event model

## 7.1 External events

External events are produced by the user, client, tool runner, or system.

Supported external events:

- `USER_MESSAGE_RECEIVED`
- `USER_APPROVED`
- `USER_REJECTED`
- `USER_PERMISSION_GRANTED`
- `USER_PERMISSION_DENIED`
- `TOOL_EXECUTION_STARTED`
- `TOOL_EXECUTION_SUCCEEDED`
- `TOOL_EXECUTION_FAILED`
- `SUBTASK_STARTED`
- `SUBTASK_COMPLETED`
- `SUBTASK_FAILED`
- `SESSION_ABORT_REQUESTED`
- `SESSION_PAUSE_REQUESTED`
- `SESSION_RESUME_REQUESTED`
- `STREAM_INTERRUPTED`
- `RECOVERY_REQUESTED`
- `TIMEOUT_OCCURRED`

## 7.2 Model-derived events

Model-derived events come from normalized model output.

Supported model-derived events:

- `MODEL_TEXT_EMITTED`
- `MODEL_TOOL_CALL_PROPOSED`
- `MODEL_ENTER_PLAN_PROPOSED`
- `MODEL_EXIT_PLAN_PROPOSED`
- `MODEL_REQUEST_APPROVAL_PROPOSED`
- `MODEL_REQUEST_PERMISSION_PROPOSED`
- `MODEL_START_SUBTASK_PROPOSED`
- `MODEL_COMPLETE_PROPOSED`
- `MODEL_ABORT_PROPOSED`
- `MODEL_INVALID_RUNTIME_ACTION`

## 7.3 Internal runtime events

Internal events are produced by the runtime.

Supported internal events:

- `STATE_TRANSITION_APPLIED`
- `ACTION_REJECTED`
- `ACTION_CONSUMED`
- `ACTION_FORWARDED`
- `STREAM_TERMINATED_BY_RUNTIME`
- `SESSION_CHECKPOINT_CREATED`
- `RECOVERY_COMPLETED`
- `RECOVERY_FAILED`

---

## 8. Transition rules

## 8.1 General rules

Every transition must satisfy:

- a valid source state,
- a valid triggering event,
- guard conditions,
- deterministic side effects,
- a valid target state.

Invalid transition attempts must never mutate state.

## 8.2 Canonical transition table

### From `IDLE`

Allowed:
- `USER_MESSAGE_RECEIVED` → `PLANNING` or `EXECUTING` depending on runtime policy / request type
- `RECOVERY_REQUESTED` → `RECOVERING`

Forbidden:
- approval results
- permission results
- subtask completions
- completion finalization
- tool execution results

### From `PLANNING`

Allowed:
- `MODEL_TEXT_EMITTED` → stay `PLANNING`
- `MODEL_REQUEST_APPROVAL_PROPOSED` → `AWAITING_APPROVAL`
- `MODEL_EXIT_PLAN_PROPOSED` → `EXECUTING` or `COMPLETING` depending on approved plan/execution readiness
- `SESSION_ABORT_REQUESTED` → `ABORTED`
- `STREAM_INTERRUPTED` → `INTERRUPTED`

Forbidden:
- direct ordinary side-effectful tool execution unless explicitly allowed by policy
- subtask completion without delegation state
- completion without valid finalization guard

### From `AWAITING_APPROVAL`

Allowed:
- `USER_APPROVED` → back to `PLANNING` or `EXECUTING` based on pending gated action
- `USER_REJECTED` → `PLANNING`, `PAUSED`, or `ABORTED` depending on policy
- `SESSION_ABORT_REQUESTED` → `ABORTED`
- `TIMEOUT_OCCURRED` → `PAUSED` or `FAILED`

Forbidden:
- ordinary tool execution
- permission resolution
- finalization

### From `AWAITING_PERMISSION`

Allowed:
- `USER_PERMISSION_GRANTED` → `EXECUTING`
- `USER_PERMISSION_DENIED` → `PAUSED`, `PLANNING`, or `ABORTED`
- `SESSION_ABORT_REQUESTED` → `ABORTED`

Forbidden:
- new ordinary tool execution before permission
- completion

### From `EXECUTING`

Allowed:
- `MODEL_TEXT_EMITTED` → stay `EXECUTING`
- `MODEL_TOOL_CALL_PROPOSED` → `EXECUTING_TOOL`
- `MODEL_REQUEST_APPROVAL_PROPOSED` → `AWAITING_APPROVAL`
- `MODEL_REQUEST_PERMISSION_PROPOSED` → `AWAITING_PERMISSION`
- `MODEL_START_SUBTASK_PROPOSED` → `ORCHESTRATING`
- `MODEL_COMPLETE_PROPOSED` → `COMPLETING`
- `SESSION_PAUSE_REQUESTED` → `PAUSED`
- `SESSION_ABORT_REQUESTED` → `ABORTED`
- `STREAM_INTERRUPTED` → `INTERRUPTED`

### From `EXECUTING_TOOL`

Allowed:
- `TOOL_EXECUTION_SUCCEEDED` → `EXECUTING`
- `TOOL_EXECUTION_FAILED` → `EXECUTING`, `FAILED`, or `AWAITING_APPROVAL` depending on retry/escalation policy
- `TIMEOUT_OCCURRED` → `FAILED` or `PAUSED`
- `SESSION_ABORT_REQUESTED` → `ABORTED`

Forbidden:
- concurrent second tool start unless explicitly allowed and modeled

### From `ORCHESTRATING`

Allowed:
- `SUBTASK_STARTED` → `AWAITING_SUBTASK`
- `MODEL_TEXT_EMITTED` → stay `ORCHESTRATING`
- `MODEL_COMPLETE_PROPOSED` → only if all subtasks resolved and no pending blockers
- `SESSION_ABORT_REQUESTED` → `ABORTED`

### From `AWAITING_SUBTASK`

Allowed:
- `SUBTASK_COMPLETED` → `ORCHESTRATING` or `EXECUTING`
- `SUBTASK_FAILED` → `ORCHESTRATING`, `FAILED`, or `AWAITING_APPROVAL`
- `SESSION_ABORT_REQUESTED` → `ABORTED`
- `TIMEOUT_OCCURRED` → `PAUSED` or `FAILED`

### From `PAUSED`

Allowed:
- `SESSION_RESUME_REQUESTED` → prior resumable state
- `SESSION_ABORT_REQUESTED` → `ABORTED`
- `RECOVERY_REQUESTED` → `RECOVERING`

### From `COMPLETING`

Allowed:
- internal finalization success → `COMPLETED`
- finalization failure → `FAILED`
- rollback/resume policy → `EXECUTING` only if completion not committed

### From `INTERRUPTED`

Allowed:
- `RECOVERY_REQUESTED` → `RECOVERING`
- `SESSION_ABORT_REQUESTED` → `ABORTED`

### From `RECOVERING`

Allowed:
- `RECOVERY_COMPLETED` → restored state
- `RECOVERY_FAILED` → `FAILED`

Terminal:
- `COMPLETED`
- `FAILED`
- `ABORTED`

---

## 9. Runtime action classes

The system must distinguish these action classes:

1. `ORDINARY_TOOL_CALL`
2. `STATE_TRANSITION_ACTION`
3. `APPROVAL_ACTION`
4. `PERMISSION_ACTION`
5. `ORCHESTRATION_ACTION`
6. `FINALIZATION_ACTION`
7. `ABORT_ACTION`
8. `INVALID_ACTION`

The action classifier must not directly execute actions. It only produces normalized actions consumed by the state machine.

---

## 10. Control semantics

## 10.1 Plan mode semantics

Plan mode is runtime-owned.

Requirements:

- entering plan mode must create a persisted state transition,
- the model may not self-exit planning without runtime validation,
- plan mode must support approval gating,
- plan mode must forbid unauthorized side-effectful tool execution unless explicit policy allows it.

## 10.2 Approval semantics

Approval gating must support:

- pending approval object,
- reason / description,
- source action reference,
- explicit approved/rejected outcome,
- timeout / expiration,
- deterministic resume path after resolution.

## 10.3 Permission semantics

Permission gating must support:

- permission request object,
- requested capability,
- requested scope,
- granted/denied result,
- explicit logging,
- retry policy,
- denial fallback path.

## 10.4 Delegation semantics

Delegation must support:

- delegated task id,
- parent-child task relation,
- delegated task status,
- completion/failure reporting,
- aggregation into parent orchestration state,
- no silent completion.

## 10.5 Completion semantics

Completion is not “model said done”.

Completion requires:

- no pending approval,
- no pending permission,
- no active tool execution,
- no unresolved subtasks,
- state transition into `COMPLETING`,
- persisted completion record,
- then transition to `COMPLETED`.

---

## 11. Streaming semantics

Streaming is first-class and must obey runtime rules.

## 11.1 Streaming invariants

1. Streaming must not bypass runtime enforcement.
2. Runtime-control outputs must be intercepted before client emission.
3. Ordinary tool-use blocks may be forwarded only if valid in current state.
4. Runtime-generated stream termination must produce a deterministic SSE error or runtime event frame.
5. No buffering of the entire upstream response is allowed unless explicitly required for correctness and limited in scope.

## 11.2 Stream pipeline

Required stream pipeline:

`provider.stream`
→ `normalize_stream`
→ `runtime_action_extract_and_classify`
→ `state_machine_enforce`
→ `forward / consume / synthesize`
→ `sequencer`
→ `sse_encoder`

## 11.3 Stream-time action handling

For each streamed block:

- if text: forward unless suppressed by compatibility policy,
- if ordinary tool call valid in current state: forward,
- if runtime-control action: consume internally, do not forward as ordinary tool call,
- if invalid action: emit deterministic runtime error handling per policy.

## 11.4 Mid-stream error semantics

If a blocking runtime violation occurs after stream start:

- do not raise raw server exceptions after response start,
- terminate through a valid SSE error frame,
- persist the failed event,
- move session into `FAILED`, `PAUSED`, or `INTERRUPTED` according to policy.

---

## 12. Persistence and recovery

## 12.1 Persistence requirements

The runtime must persist:

- session metadata,
- current state,
- current pending approval object,
- current pending permission object,
- active tasks/subtasks,
- event log,
- checkpoints,
- last committed turn boundary.

## 12.2 Event log model

Event log entries must include:

- monotonic sequence id,
- session id,
- turn id,
- timestamp,
- event type,
- payload,
- pre-state,
- post-state,
- decision metadata,
- correlation ids.

## 12.3 Recovery

Recovery must support:

- replay from event log,
- checkpoint restore with replay tail,
- interrupted stream restoration,
- restoration of approval/permission/subtask blockers,
- deterministic rebuild of current state.

The runtime must never guess restored state from message history alone.

---

## 13. Policy model

Policies are runtime configuration, not hardcoded behavior.

Required policy domains:

- ordinary tool allow/block rules,
- plan-time execution policy,
- approval gating policy,
- permission gating policy,
- orchestration policy,
- finalization policy,
- invalid action handling policy,
- text-based emulation detection policy,
- stream violation handling policy,
- recovery strictness policy.

Each policy must support at least:

- `ALLOW`
- `WARN`
- `BLOCK`

Some domains may additionally support:
- `CONSUME`
- `ESCALATE`
- `PAUSE`

---

## 14. Error model

The runtime must define explicit error classes for:

- invalid state transition,
- unexpected external event,
- invalid runtime action,
- duplicate event application,
- missing pending approval,
- missing pending permission,
- tool result without in-flight tool,
- subtask completion without active subtask,
- finalization with unresolved blockers,
- recovery inconsistency,
- stream/runtime protocol mismatch,
- provider/model drift against runtime contract.

All runtime errors must be serializable and auditable.

---

## 15. Required implementation modules

The implementation must be separated by responsibility.

## 15.1 Mandatory modules

### `runtime/state.py`
Defines:
- runtime states,
- mode flags,
- pending objects,
- session runtime snapshot,
- invariants.

### `runtime/events.py`
Defines:
- external events,
- model-derived events,
- internal events,
- event payload types.

### `runtime/actions.py`
Defines:
- normalized runtime actions,
- action taxonomy,
- action metadata.

### `runtime/classifier.py`
Classifies model output into:
- ordinary tool action,
- runtime action,
- invalid action,
- text emulation candidate.

### `runtime/state_machine.py`
Owns:
- transition table,
- guards,
- side effects,
- transition application,
- invariant validation.

### `runtime/session_store.py`
Owns:
- session persistence,
- load/save/update,
- checkpoint operations.

### `runtime/event_log.py`
Owns:
- append-only event logging,
- replay interfaces,
- correlation metadata.

### `runtime/orchestrator.py`
Owns:
- per-turn orchestration,
- routing between classifier, state machine, persistence, and stream handling.

### `runtime/stream.py`
Owns:
- streaming enforcement wrapper,
- mid-stream runtime error handling,
- streaming action consumption/forwarding logic.

### `runtime/recovery.py`
Owns:
- checkpoint restore,
- replay,
- interrupted-session restoration.

### `runtime/policies.py`
Owns:
- policy resolution,
- per-model policy overlays,
- default policy sets.

### `runtime/errors.py`
Owns:
- runtime-specific error taxonomy.

---

## 16. Required invariants

The implementation must enforce these invariants at runtime:

1. At most one active top-level state per session.
2. Pending approval exists iff state is `AWAITING_APPROVAL`.
3. Pending permission exists iff state is `AWAITING_PERMISSION`.
4. In-flight tool exists iff state is `EXECUTING_TOOL`.
5. Active unresolved subtask count > 0 iff state is `AWAITING_SUBTASK` or `ORCHESTRATING`.
6. Completion cannot commit while blockers exist.
7. No runtime-control action may directly mutate state without event log append.
8. No forwarded tool call may violate current state policy.
9. Stream-time consumed runtime-control actions must not leak as forwarded ordinary tools.
10. Recovery must rebuild a valid invariant-satisfying state or fail explicitly.

---

## 17. Testing requirements

No implementation is acceptable without the full test matrix below.

## 17.1 Unit tests

Required coverage:

- classifier correctness,
- state transition correctness,
- invalid transition rejection,
- policy resolution,
- approval lifecycle,
- permission lifecycle,
- delegation lifecycle,
- completion lifecycle,
- recovery replay correctness,
- invariant checks,
- streaming enforcement behavior.

## 17.2 Integration tests

Required coverage:

- end-to-end planning lifecycle,
- approval flow,
- permission flow,
- tool execution flow,
- orchestration/subtask flow,
- completion flow,
- pause/resume flow,
- stream-time runtime-action consumption,
- mid-stream block/error behavior,
- interrupted-session recovery.

## 17.3 E2E tests

Required coverage against real non-Claude models:

- plan proposal then approval,
- permission-gated execution,
- normal tool execution,
- delegated subtask orchestration,
- completion after multi-step execution,
- invalid runtime action rejection,
- recovery after interrupted stream,
- repeated long-session continuity.

## 17.4 Property / invariant tests

Required:
- replay preserves final state,
- invalid event orders do not mutate session,
- duplicate events are idempotently rejected or safely handled,
- stream enforcement does not drain upstream eagerly.

---

## 18. Performance requirements

This runtime must be production-ready, not only correct.

Requirements:

- O(1) or amortized O(1) state lookup by session id,
- append-only event log writes,
- minimal per-event allocations,
- no full-response buffering in standard streaming path,
- no repeated reclassification of already-normalized blocks,
- no duplicated state derivation passes,
- checkpointing designed to reduce full replay cost,
- structured logging without hot-path waste.

---

## 19. Security and safety requirements

The runtime must:

- never allow the model to self-grant permissions,
- never allow uncontrolled state mutation from plain text,
- never treat bash/text emulation as authoritative runtime state change,
- never finalize with unresolved blockers,
- never delegate tasks without persisted task identity,
- never lose state consistency after blocked or malformed actions.

---

## 20. Implementation order

Implementation must proceed in this order:

1. state model
2. event model
3. action model
4. classifier
5. state machine
6. persistence + event log
7. orchestrator
8. streaming enforcement integration
9. recovery system
10. tests
11. real-model E2E validation

No step may skip tests for previous layers.

---

## 21. Acceptance criteria

This specification is satisfied only if all conditions below are true:

1. Runtime state is proxy-owned and persisted.
2. All listed states are implemented.
3. All listed event classes are implemented.
4. All transition guards are enforced.
5. Runtime-control actions are consumed internally, not leaked as ordinary tools.
6. Streaming path enforces the same runtime semantics as non-stream path.
7. Mid-stream violations terminate safely without raw response-started exceptions.
8. Approval, permission, orchestration, completion, pause, abort, interruption, and recovery all exist as real runtime flows.
9. Recovery reconstructs valid state from persisted data.
10. Unit, integration, and E2E suites pass.
11. The system works with non-Claude models without relying on native Claude runtime semantics.
12. The implementation is modular, deterministic, auditable, and production-ready.

---

## 22. Final note

This runtime is not a heuristic patch layer.

It is a **full orchestration substrate** that replaces missing native Claude runtime semantics when the upstream model does not provide them.

Anything less than the full state machine, full event system, full transition enforcement, full streaming integration, and full persistence/recovery is out of spec.