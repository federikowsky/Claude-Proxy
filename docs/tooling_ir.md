# LLM-Proxy — Claude Code Compatibility Runtime Bridge
## Freeze Specification
### Status: Canonical Implementation Spec
### Scope: Production-ready feature, not demo, not MVP, not V0

## 1. Objective

We want Claude Code to work reliably with **non-Claude models** routed through our proxy, including OpenRouter-hosted models, without depending on those models to correctly understand or reproduce Claude Code’s hidden runtime semantics.

The goal is **not** to ask the model to “behave better”.
The goal is to build a **runtime compatibility architecture** that makes the system robust even when the backing model is weaker, inconsistent, or partially incompatible.

This feature must make Claude Code + non-Claude models operationally usable for real agentic workflows, with strong correctness guarantees around tool calling, protocol shaping, state/control transitions, and error handling.

This is a **serious production feature**.
It must be implemented as infrastructure/runtime behavior, not as a prompt hack.

---

## 2. Non-Goals

This feature must **not**:

- become a fake assistant that replaces the model’s reasoning with hardcoded business logic
- become a brittle prompt-only workaround
- introduce ad hoc special cases only for Nemotron
- support only a subset of Claude Code capabilities
- silently degrade critical control-flow semantics
- rely on undocumented best-effort behavior from weak models
- become an overgrown orchestration framework that duplicates Claude Code itself

This system is a **compatibility runtime bridge**, not a second assistant.

---

## 3. Core Product Requirement

The bridge must support **the full operational surface that Claude Code expects to expose through the messages/tooling protocol**, including:

- ordinary tool calls
- structured tool input generation
- tool streaming payload continuity
- state/control transition semantics
- completion/finalization semantics
- orchestration/delegation semantics
- message/content block correctness
- count_tokens compatibility paths
- model/provider quirks normalization
- defensive validation and repair where safe
- hard failure where safety/correctness would otherwise be violated

The implementation must be **universal**, not model-specific.
Model-specific behavior is allowed only through explicit capability metadata and adapter rules.

---

## 4. Architectural Direction

## 4.1 High-Level Principle

We must stop treating the proxy as a transparent pass-through once the backing model is non-native.

Instead, the proxy must become a **runtime contract enforcer**.

Meaning:

- the **model still decides content and intent**
- the **proxy guarantees contract-correct execution shape**
- the **proxy owns normalization, validation, safe repair, control semantics enforcement, and provider adaptation**

The proxy must not invent user intent.
The proxy must ensure that the model’s output is converted into something **valid, safe, and executable under Claude Code expectations**.

---

## 4.2 Required Runtime Layers

The implementation must converge toward these logical layers:

### A. Ingress Contract Layer
Responsible for:
- validating incoming Anthropic-compatible request shape
- preserving accepted extension fields
- normalizing request payloads into internal canonical structures
- rejecting invalid shapes early with precise errors

### B. Canonical IR Layer
A single internal representation for:
- requests
- tools
- tool schemas
- content blocks
- deltas
- control/state actions
- orchestration actions
- response events

This IR must be the internal source of truth.
All providers/adapters must translate **to/from** it.

### C. Capability Registry Layer
Responsible for explicit model/provider capability metadata:
- tool support
- stream/non-stream support
- thinking passthrough policy
- unsupported request fields
- schema strictness
- control-action reliability level
- orchestration reliability level
- provider-specific quirks

No hidden capability inference in hot paths.

### D. Request Preparation Layer
Responsible for:
- per-model field stripping
- safe request rewriting
- tool schema normalization
- contract shim injection only where strictly needed
- provider-safe payload preparation

### E. Runtime Contract Enforcement Layer
Responsible for:
- validating model-emitted tool usage
- detecting invalid control-flow/tool misuse
- classifying unsafe generic-tool emulation attempts
- mapping recognized control/orchestration intent into canonical runtime actions
- refusing invalid or ambiguous transitions safely

This is one of the most important layers.

### F. Provider Adapter Layer
Responsible for:
- provider-specific request translation
- provider-specific event normalization
- SSE parsing and normalization
- non-stream normalization
- usage extraction
- count_tokens adaptation
- upstream error translation

### G. Execution / Policy Layer
Responsible for:
- deciding what is executable
- deciding what is repairable
- deciding what must fail hard
- enforcing invariants before provider boundary and before client boundary

### H. Egress Compatibility Layer
Responsible for:
- emitting Anthropic-compatible messages/events
- sequencing content block events safely
- preserving tool-use semantics
- preserving message stop semantics
- suppressing incompatible internal/provider-only artifacts where necessary

---

## 5. Canonical Internal Model Requirement

The system must move toward a **full canonical IR**, not partial scattered heuristics.

At minimum, the canonical IR must represent:

### 5.1 Request IR
- model target
- message list
- system blocks
- metadata
- temperature/top_p/max_tokens
- stop sequences
- tools
- tool choice
- thinking config
- stream mode
- passthrough extensions
- provider request context

### 5.2 Tool IR
- tool name
- description
- normalized input schema
- extras
- tool category
- execution sensitivity
- whether it is:
  - generic
  - state/control
  - orchestration
  - normal dedicated runtime tool

### 5.3 Action IR
A canonical action model must exist for non-ordinary tool semantics:

- `TOOL_CALL`
- `STATE_TRANSITION`
- `ORCHESTRATION_ACTION`
- `FINALIZATION_ACTION`
- `NO_OP`
- `INVALID_ACTION`

This is critical.
Do **not** leave control semantics encoded only as fragile string heuristics in many places.

### 5.4 Response/Event IR
Must canonically represent:
- message start
- content block start
- content deltas
- content block stop
- message delta
- message stop
- errors
- warnings
- ping
- provider/native thinking distinctions
- tool-use deltas

---

## 6. Control / State Semantics

## 6.1 Problem
Non-Claude models often fail to correctly use Claude Code control/state tools or emulate them incorrectly with:
- Bash
- plain text
- fake completion text
- pseudo-confirmation messages
- shell echo/printf tricks

## 6.2 Required Solution
The proxy must explicitly model **control/state semantics**.

It must:
- identify control/state tools from registry/classification
- identify runtime-control intent from model output
- detect invalid emulation attempts
- map valid control intent into canonical state actions
- refuse ambiguous unsafe cases

## 6.3 Hard Rule
The model must not be allowed to “fake” a runtime transition with:
- Bash
- plain text
- generic tool misuse
- pseudo-tool narration

If the action is a real runtime transition, it must either:
- be represented as a valid runtime action
- or fail clearly

Never silently accept fake state changes.

---

## 7. Orchestration Semantics

## 7.1 Problem
Subagent/handoff/task-delegation style actions are also often mishandled by weaker models.

## 7.2 Required Solution
The proxy must classify orchestration actions explicitly and treat them as first-class runtime semantics, not ordinary generic tool calls.

Must support:
- detection
- validation
- normalization
- explicit action shaping
- safe rejection if malformed

---

## 8. Tool Schema Reliability

## 8.1 Requirement
Every tool that reaches provider boundary must have a valid normalized schema.

## 8.2 Required Behavior
Implement deterministic normalization:
- missing schema -> fallback object schema
- invalid schema type -> fallback object schema
- object-like hints without explicit `type` -> inject `type: object`
- object schema without `properties` -> inject empty properties
- sanitize malformed `required`
- preserve unknown extra keys where safe

## 8.3 Invariant
At provider boundary:
- no tool may be emitted with invalid/non-mapping schema
- invariant violation must raise internal bridge error immediately

This is non-negotiable.

---

## 9. Repair vs Hard Failure Policy

The system must use a strict policy:

## 9.1 Safe Repair Allowed
Only when transformation is deterministic and semantics-preserving, for example:
- tool schema normalization
- removal of model-unsupported request fields
- provider event normalization
- block sequencing repair
- reasoning/thinking mapping where explicitly configured

## 9.2 Hard Failure Required
When correctness or runtime semantics would otherwise be faked or guessed, for example:
- ambiguous control transition
- malformed orchestration action
- invalid provider boundary invariant
- impossible tool payload shape
- conflicting runtime action interpretation

If the system cannot guarantee safe correctness, it must fail loudly and precisely.

---

## 10. Model Capability Registry

The feature must introduce or strengthen a capability-driven design.

Every model config must be able to declare at least:

- `supports_stream`
- `supports_nonstream`
- `supports_tools`
- `supports_thinking`
- `thinking_passthrough_mode`
- `unsupported_request_fields`
- `schema_normalization_policy`
- `control_action_policy`
- `orchestration_action_policy`
- `generic_tool_emulation_policy`

This can start with reasonable defaults, but the architecture must support it cleanly.

Do not bury behavior in ad hoc if/else branches spread across unrelated files.

---

## 11. Observability and Diagnostics

Production readiness requires strong observability.

Must add structured logging for:
- stripped request fields
- tool schema normalization events
- control action classification decisions
- orchestration classification decisions
- generic-tool emulation detection
- repair applied vs hard failure
- provider boundary invariant failures
- upstream/provider protocol anomalies

Logs must be:
- low-noise
- structured
- cheap enough for production
- gated appropriately by level

---

## 12. Performance and Design Constraints

Implementation must follow:

- SOLID
- DRY
- KISS
- SRP

And specifically:

- avoid repeated reclassification in hot paths
- compute normalized tool metadata once where possible
- avoid unnecessary request rebuilds
- preserve object identity when unchanged
- minimize allocations in stream paths
- avoid regex-heavy repeated scanning if a cheaper classification path is possible
- prefer deterministic tables/sets/enums over repeated stringly-typed logic
- use compact, readable, production-grade code
- prefer architectural clarity over prompt hacks

No over-engineered framework explosion.
No giant god-classes.

---

## 13. File/Module Responsibilities

The implementation should evolve cleanly around responsibilities similar to:

- `domain/models.py`
  - canonical data structures only

- `domain/serialization.py`
  - canonical parsing/serialization
  - schema normalization helpers

- `domain/errors.py`
  - precise domain and bridge errors

- `application/request_preparer.py`
  - request shaping, schema normalization, field stripping, shim injection

- `application/services.py`
  - service orchestration and contract enforcement coordination
  - not giant low-level parsing logic

- `application/policies.py`
  - compatibility behavior, normalization policies, sequencing policies

- `application/runtime_actions.py` or equivalent new module
  - canonical action classification and execution-shape decisions

- `application/tool_classifier.py` or equivalent new module
  - deterministic tool categorization/classification

- `infrastructure/providers/openrouter.py`
  - provider-specific translation and event normalization only

- `infrastructure/resolvers.py`
  - model resolution only

Keep responsibilities narrow and obvious.

---

## 14. Expected Outcome

After this feature is implemented correctly:

- Claude Code with non-Claude models should become **substantially more reliable**
- the system should stop depending on weak models to perfectly understand hidden Claude runtime semantics
- generic misuse of Bash/text for runtime-control should be caught
- control and orchestration semantics should become explicit runtime constructs
- provider payload validity should be guaranteed before emission
- failures should become sharper, rarer, and easier to diagnose

This does **not** mean perfect equivalence with native Claude.
It means a serious, production-grade compatibility bridge with high operational reliability.

---

## 15. Acceptance Criteria

Implementation is acceptable only if all are true:

1. No provider tool definition can leave the proxy without valid normalized schema.
2. Tool schema normalization is deterministic, tested, and logged.
3. Request preparation preserves identity when unchanged.
4. Control/state semantics are handled explicitly, not only via prompt shims.
5. Orchestration semantics are handled explicitly, not only by weak string matching in many places.
6. Fake state transitions through Bash/plain text are detected and blocked.
7. Generic tool misuse is classified safely.
8. Capability-driven behavior is explicit and configurable.
9. Provider adapters stay provider-focused and are not overloaded with global runtime logic.
10. Stream and non-stream paths both preserve correctness.
11. Count-tokens path remains valid.
12. Unit + integration tests cover repair, rejection, invariants, and representative end-to-end flows.
13. The result is production-oriented infrastructure, not a demo workaround.

---

## 16. Implementation Priority Order

Implement in this order:

1. Canonical action model for control/orchestration/finalization
2. Deterministic tool classification layer
3. Runtime contract enforcement layer
4. Capability policy extensions
5. Provider-boundary invariants and adapter tightening
6. Expanded tests
7. Final cleanup/refactor for SRP and readability

Do not start with prompt tweaks.
Do not start with provider-specific hacks.
Do not start with superficial logs only.

Build the runtime semantics first.

---

## 17. Final Directive

This feature must be implemented as a **real compatibility runtime architecture**.

It must be:
- universal
- deterministic where possible
- strict where necessary
- minimal in accidental complexity
- robust in production
- clean enough to extend to future providers/models without rewriting the system