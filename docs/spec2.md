# Claude Proxy — Specs V2
## Production-ready transparent Anthropic ↔ OpenRouter bridge
## Delta spec to apply on top of the existing implementation

> This document **supersedes the previous MVP-oriented spec wherever there is conflict**.
> The existing codebase must be **evolved**, not rewritten blindly.
> Keep the current architecture where it is sound, but remove MVP restrictions and text-only assumptions.
> The final system must act as a **transparent, loss-minimizing, protocol-faithful bridge** for Claude Code.

---

# 1. Core objective

The proxy must:

- accept requests from Claude Code using the **Anthropic Messages API shape**
- forward them to OpenRouter with the highest possible fidelity
- read OpenRouter responses/streams
- transform them into **Anthropic-valid responses/SSE**
- preserve **all Claude Code functionality that is representable**
- suppress/reshape only provider-specific constructs that would otherwise break Claude Code

The proxy must **not**:

- intentionally reduce behavior to text-only
- intentionally disable tools, content blocks, or stream modes
- introduce product concerns such as auth, authorization, rate limiting, multi-tenant control, quotas, etc.

The proxy is a **protocol bridge**, not a gateway product.

---

# 2. Non-negotiable product rules

## 2.1 Transparency first
The bridge must preserve as much of the Anthropic protocol semantics as possible.

This includes, where representable:

- `text`
- `tool_use`
- `tool_result`
- `thinking`
- usage
- stop reasons
- system prompts
- metadata
- stop sequences
- mixed multi-block content
- streaming and non-streaming modes

## 2.2 Loss minimization
The proxy must not drop data by default.

Transformation order must always be:

1. preserve as-is if valid
2. map to Anthropic-equivalent representation if possible
3. only if impossible and client-breaking: suppress or normalize

## 2.3 No feature regression
Anything Claude Code already expects from Anthropic Messages must remain available unless the upstream provider/model fundamentally cannot supply it.

## 2.4 No product-layer extras
Do not add:
- authentication / authorization
- rate limiting
- tenant isolation
- request correlation requirements as product logic
- user management
- dashboard/admin features

Minimal internal logging/diagnostics is fine, but not as a product concern.

---

# 3. Scope expansion from V1

The current implementation is MVP-oriented and too restrictive.
The following restrictions must be removed.

## 3.1 Remove text-only assumptions
The bridge must support all relevant message content block types that Claude Code may use.

At minimum:

- `text`
- `tool_use`
- `tool_result`
- `thinking`

## 3.2 Remove stream-only assumption
The bridge must support:

- `stream=true`
- `stream=false`

## 3.3 Remove "drop everything except safe text" architecture
The existing stream normalizer/encoder must be refactored to preserve structured content blocks and deltas.

## 3.4 Preserve request richness
Requests must preserve and forward:

- `system`
- `messages`
- `metadata`
- `temperature`
- `top_p` if present
- `max_tokens`
- `stop_sequences`
- `tools`
- `tool_choice`
- `thinking` config if present and representable
- provider-specific passthrough metadata where explicitly allowed by config

---

# 4. Required compatibility target

The proxy must be compatible with Claude Code behavior expectations for the Anthropic Messages API.

That means:

- request body shape must remain Anthropic-compatible
- streaming event ordering must remain Anthropic-valid
- non-stream responses must remain Anthropic-valid
- tool use must remain structurally usable by Claude Code
- content blocks must preserve indices and ordering
- reasoning/thinking must not be accidentally rendered as final text

---

# 5. Implementation strategy: evolve, do not rewrite blindly

The existing repository already contains useful foundations:
- FastAPI app
- route wiring
- domain model foundation
- service orchestration
- OpenRouter adapter
- SSE parsing
- tests

You must keep and evolve the current architecture where appropriate.

Refactor only where needed to:
- generalize the domain
- remove MVP assumptions
- preserve structured blocks
- support both streaming and non-streaming
- support loss-minimizing protocol translation

---

# 6. Architectural target

Use a layered architecture with clear boundaries.

## 6.1 Layers

### API layer
Responsibilities:
- HTTP endpoints
- request schema validation
- response shaping
- streaming responses

### Application layer
Responsibilities:
- orchestration
- provider/model selection
- normalization policy selection
- stream and non-stream execution paths

### Domain layer
Responsibilities:
- canonical internal models
- provider-agnostic event model
- ports/interfaces
- transformation invariants

### Infrastructure layer
Responsibilities:
- OpenRouter adapter
- request translation
- SSE parser
- response normalizer
- shared HTTP client
- config

---

# 7. Required design correction

## 7.1 Current problem
The current implementation forwards only text in practice.
That is unacceptable.

## 7.2 Required correction
Introduce a **full canonical event/content model** that can represent:

- full messages
- content blocks
- block deltas
- usage
- stop reasons
- provider warnings
- errors
- thinking/reasoning separately from final text
- tool use and tool result

Do not collapse everything into plain text.

---

# 8. Canonical domain model requirements

## 8.1 Canonical request model
The internal request model must support, at minimum:

- `model: str`
- `messages: tuple[Message, ...]`
- `system: Sequence[ContentBlock] | None`
- `metadata: Mapping[str, Any] | None`
- `temperature: float | None`
- `top_p: float | None`
- `max_tokens: int`
- `stop_sequences: tuple[str, ...]`
- `tools: tuple[ToolDefinition, ...]`
- `tool_choice: ToolChoice | None`
- `thinking: ThinkingConfig | None`
- `stream: bool`

## 8.2 Canonical message model
Each message must support:
- `role`
- ordered content blocks

## 8.3 Canonical content blocks
At minimum, represent:
- `TextBlock`
- `ToolUseBlock`
- `ToolResultBlock`
- `ThinkingBlock`
- `UnknownBlock` for forward compatibility

Do not reduce content to a single `text: str`.

## 8.4 Canonical streaming event model
Must support all relevant Anthropic-style events:

- `MessageStartEvent`
- `ContentBlockStartEvent`
- `ContentBlockDeltaEvent`
- `ContentBlockStopEvent`
- `MessageDeltaEvent`
- `MessageStopEvent`
- `PingEvent`
- `ErrorEvent`

And deltas must support:
- `TextDelta`
- `InputJsonDelta`
- `ThinkingDelta`
- `SignatureDelta`
- `UnknownDelta`

## 8.5 Usage model
Usage must preserve:
- input tokens if available
- output tokens if available
- reasoning tokens if available
- cached token details if available
- provider-specific extra usage fields in a typed extension payload

## 8.6 Stop reasons
Preserve stop reasons from upstream and map them to Anthropic-compatible values when possible.
Do not silently discard them.

---

# 9. Request handling requirements

## 9.1 Supported request fields
The proxy must parse and preserve:

- `model`
- `messages`
- `system`
- `metadata`
- `temperature`
- `top_p`
- `max_tokens`
- `stop_sequences`
- `stream`
- `tools`
- `tool_choice`
- `thinking`
- any future Anthropic-compatible fields through a controlled passthrough container if safe to do so

## 9.2 Request validation philosophy
Validation must ensure the request is structurally valid.

Validation must **not** reject features simply because the old MVP did not support them.

Reject only if:
- request is malformed
- a field is fundamentally unsupported by the configured provider bridge
- a field cannot be represented or forwarded under current adapter capabilities

## 9.3 Unknown future fields
Unknown fields must be handled carefully:
- either preserved in an extension map
- or rejected explicitly with a clear error
- never silently ignored if they affect semantics

---

# 10. Response handling requirements

## 10.1 Streaming responses
Streaming must preserve structured semantics.

The bridge must generate Anthropic-valid SSE sequences including:
- `message_start`
- `content_block_start`
- `content_block_delta`
- `content_block_stop`
- `message_delta`
- `message_stop`
- `ping` when appropriate
- `error` on controlled failures

## 10.2 Non-stream responses
For `stream=false`, the bridge must emit a proper Anthropic response object:
- top-level message object
- ordered content blocks
- usage
- stop reason
- metadata where applicable

## 10.3 Block fidelity
Do not merge all content blocks into a single text block unless there is no alternative.

The proxy must preserve:
- block order
- block type
- block identity/index
- tool ids/names/inputs
- thinking boundaries where representable

---

# 11. Thinking / reasoning requirements

## 11.1 Principle
Thinking must be treated as first-class structured content, not as plain text.

## 11.2 Anthropic-compatible thinking
If upstream data can be represented as Anthropic `thinking` content blocks and/or `thinking_delta` / `signature_delta`, preserve it.

## 11.3 OpenRouter-specific reasoning data
If OpenRouter returns provider-specific reasoning structures that are not already Anthropic-native:

1. attempt loss-minimizing mapping into Anthropic-compatible thinking structures
2. preserve ordering relative to text/tool blocks if representable
3. never coerce reasoning into final text
4. only suppress if it cannot be represented validly and would break Claude Code

## 11.4 Fallback policy
There may be a compatibility mode that suppresses non-representable reasoning chunks.
This must **not** be the default if transparent mapping is possible.

## 11.5 Absolutely forbidden
- putting reasoning into final text
- exposing provider-native unsupported reasoning chunk types directly to Claude Code
- flattening thinking into assistant final answer

---

# 12. Tooling requirements

## 12.1 Tool definitions
The request path must preserve and forward tool definitions.

## 12.2 Tool choice
Preserve `tool_choice` semantics.

## 12.3 Tool use blocks
Streaming and non-streaming responses must preserve:
- tool use block type
- tool use id
- tool name
- tool input
- partial JSON deltas where streamed

## 12.4 Tool result blocks
Requests containing tool results must be preserved and forwarded correctly.

## 12.5 Streaming JSON input deltas
If the upstream provider supplies incremental tool input JSON, map it to Anthropic-compatible `input_json_delta` events rather than collapsing it to final text.

---

# 13. Protocol translation requirements

## 13.1 General philosophy
The bridge is not a generic text reformatter.
It is a protocol translator.

## 13.2 Request translation
The OpenRouter adapter must map the canonical request model into a provider request without losing supported semantics.

## 13.3 Response translation
The OpenRouter adapter must map provider responses/chunks into canonical events/content blocks first.

Only then may the Anthropic encoder emit final wire format.

Do not couple OpenRouter parsing directly to Anthropic SSE emission.

## 13.4 Unknown provider events
Provider unknown events must not crash the bridge.

Handle them by:
- classifying as `UnknownProviderEvent`
- preserving them in diagnostics
- discarding only at the final bridge boundary if no valid mapping exists

---

# 14. Compatibility modes

Add a configurable compatibility mode system.

## 14.1 Modes

### `transparent`
Default mode.
Behavior:
- preserve all representable semantics
- only normalize provider-specific incompatibilities
- no arbitrary dropping

### `compat`
More aggressive client-protection mode.
Behavior:
- suppress non-representable or client-breaking structures more aggressively
- still preserve text, tools, usage, stop reasons, and all representable content

### `debug`
Same as transparent, but with additional diagnostics/logging and optional event traces.
Never log secrets.

## 14.2 Default
Default mode must be `transparent`.

---

# 15. Current code refactor plan

Apply these concrete changes to the current codebase.

## 15.1 `claude_proxy/domain/models.py`
Refactor the domain model from text-centric to structured canonical content.

Required additions:
- content block hierarchy
- tool definitions
- tool choice model
- thinking config model
- usage detail model
- non-stream response model
- richer streaming event model
- unknown block/event representations

Keep:
- `dataclass(slots=True)` where appropriate
- immutable structures where possible

## 15.2 `claude_proxy/domain/ports.py`
Update ports to support:
- stream and non-stream completions
- richer event/content structures
- capability-aware provider behavior

Suggested ports:
- `ModelProvider.stream(...)`
- `ModelProvider.complete(...)`
- `RequestTranslator`
- `ResponseNormalizer`
- `SseEncoder`
- `ResponseEncoder`

## 15.3 `claude_proxy/application/services.py`
Refactor service orchestration to:
- support both stream and non-stream flows
- preserve full canonical content
- select compatibility mode
- invoke translation + normalization + encoding in separate steps
- avoid text-only aggregation

## 15.4 `claude_proxy/application/policies.py`
Replace MVP-style drop policies with transparent compatibility policies.

Required policy families:
- reasoning mapping policy
- unknown event handling policy
- block preservation policy
- compatibility mode policy

## 15.5 `claude_proxy/application/sse.py`
Refactor SSE encoder to support:
- text blocks
- tool use blocks
- input_json_delta
- thinking_delta
- signature_delta
- usage-bearing message_delta
- correct ordering and closure

Do not hardcode a single text block assumption.

## 15.6 `claude_proxy/api/routes/messages.py`
Refactor endpoint to:
- accept full supported request schema
- support `stream=true` and `stream=false`
- return correct content type for each mode
- stop rejecting advanced fields just because of old MVP constraints

## 15.7 `claude_proxy/infrastructure/providers/openrouter.py`
Refactor adapter into clearer responsibilities, even if kept in one file temporarily:
- request translation
- provider HTTP call
- SSE parser
- provider chunk classifier
- canonical event normalizer
- non-stream response normalizer
- stop reason mapping
- usage mapping
- reasoning/thinking mapping
- tool use mapping

Long-term preferred split:
- `translator.py`
- `sse_parser.py`
- `normalizer.py`
- `provider.py`
- `error_mapper.py`

But do not force a giant rewrite if incremental refactor is better.

## 15.8 `claude_proxy/infrastructure/config.py`
Extend config to support:
- compatibility mode
- model capability metadata
- provider passthrough toggles where needed
- optional upstream feature flags

Keep config lightweight and operationally simple.

---

# 16. OpenRouter adapter requirements

## 16.1 Purpose
OpenRouter is the first provider adapter.
The adapter must be written so that future providers can be added without changing the core domain/application logic.

## 16.2 Must preserve upstream semantics where possible
Map:
- content
- tools
- thinking/reasoning
- usage
- finish reasons
- model identifier
- metadata if available

## 16.3 Streaming parser
The SSE parser must:
- work incrementally
- tolerate fragmented chunks
- tolerate keepalives
- tolerate unknown events
- not buffer the full response
- classify provider payloads accurately

## 16.4 Response normalization
The normalizer must produce canonical internal events/blocks.
Do not emit Anthropic wire format directly from provider parser code.

## 16.5 Reasoning handling
The adapter must classify provider reasoning data separately from final text and from tool data.

## 16.6 Tool handling
Tool call and tool result semantics must be preserved where OpenRouter exposes them.

---

# 17. Request/response passthrough philosophy

## 17.1 Preserve structure, not raw wire blindly
This is not raw byte passthrough.
It is structured protocol passthrough with translation.

## 17.2 Canonical-first pipeline
Always use this flow:

### Request path
Anthropic request
-> API schema
-> canonical request
-> provider request translation
-> OpenRouter call

### Stream response path
OpenRouter SSE/data
-> provider parser
-> canonical events
-> Anthropic SSE encoder
-> Claude Code

### Non-stream response path
OpenRouter response
-> provider normalizer
-> canonical response
-> Anthropic response encoder
-> Claude Code

---

# 18. Errors and robustness

## 18.1 Error philosophy
Be strict about malformed protocol, not about feature richness.

## 18.2 Client-visible errors
Return clear Anthropic-compatible error responses where applicable.

## 18.3 Upstream errors
Map OpenRouter/upstream errors into meaningful bridge errors without leaking secrets.

## 18.4 Unknown future behavior
Unknown provider events or fields must not crash the bridge.
They must either:
- be preserved in diagnostics and ignored safely
- or mapped if support is later added

---

# 19. Configuration requirements

## 19.1 Keep configuration minimal
No product-level configuration.
Only bridge-relevant configuration.

## 19.2 Required configuration fields
At minimum:
- host
- port
- log level
- OpenRouter base URL
- OpenRouter API key env var
- compatibility mode
- model registry
- optional feature flags for provider quirks

## 19.3 Model registry
Each model may declare:
- provider
- enabled
- supports_tools
- supports_thinking
- supports_nonstream
- supports_stream
- provider quirks / capability flags

This is capability metadata, not a product policy engine.

---

# 20. Performance requirements

## 20.1 General
The bridge must remain lightweight and efficient.

## 20.2 Must-do
- streaming end-to-end
- incremental parsing
- shared `httpx.AsyncClient`
- no full-response buffering in streaming mode
- no repeated re-parsing of the same payload
- one-pass event classification when practical

## 20.3 Data structures
Use:
- `dict` for registries and lookups
- tuples for immutable sequences where appropriate
- `dataclass(slots=True)` in domain/core
- generators / async generators for stream pipelines

## 20.4 Avoid
- text accumulation as the primary representation
- repeated JSON reserialization
- multiple passes over the same stream unless required by compatibility fallback

---

# 21. Logging and diagnostics

## 21.1 Purpose
Technical observability only.

## 21.2 Include
- provider
- model
- stream/non-stream mode
- compatibility mode
- latency
- upstream status
- normalization warnings
- event mapping anomalies

## 21.3 Do not include
- secrets
- API keys
- full prompts/responses by default

## 21.4 Debug mode
Allow opt-in event trace logging for difficult protocol cases.

---

# 22. Backward compatibility with current code

The refactor must preserve:
- existing health endpoint
- existing FastAPI entrypoint structure
- current test organization where still relevant
- current shared client approach
- current config loading approach if sound

But it must replace:
- text-only assumptions
- stream-only assumptions
- blanket reasoning dropping by default
- MVP validation restrictions on rich content

---

# 23. Test suite expansion requirements

The current test suite passes, but it validates an MVP.
It must be extended to validate transparent bridge behavior.

## 23.1 Keep existing useful tests
Keep existing tests that still match the new architecture.

## 23.2 Add unit tests for
- structured content block parsing
- tool definition handling
- tool use normalization
- tool result handling
- thinking block normalization
- reasoning-to-thinking mapping
- unknown provider event handling
- non-stream response mapping
- stop reason mapping
- usage mapping
- stream compatibility modes

## 23.3 Add golden streaming tests for
- text-only message
- text + thinking
- text + tool_use
- tool_use with input_json_delta
- mixed content block ordering
- unknown event interleaving
- reasoning that must be mapped
- reasoning that must be suppressed
- message_delta usage inclusion
- message_stop ordering correctness

## 23.4 Add integration tests for
- `stream=true`
- `stream=false`
- tools passthrough
- thinking passthrough/mapping
- OpenRouter error propagation
- upstream unknown chunk resilience

## 23.5 Acceptance tests
Real-client acceptance criteria must include:
- no `Unsupported content type: redacted_thinking`
- no accidental rendering of final output inside thinking
- tool use preserved
- Claude Code behavior not reduced compared to direct Anthropic-compatible expectations

---

# 24. Acceptance criteria for V2

The work is accepted only if all of the following are true.

## 24.1 Protocol transparency
The proxy no longer behaves as text-only.
Structured content is preserved.

## 24.2 Stream + non-stream
Both `stream=true` and `stream=false` work.

## 24.3 Tool preservation
`tools`, `tool_choice`, `tool_use`, and `tool_result` are preserved where representable.

## 24.4 Thinking preservation/mapping
Thinking/reasoning is handled structurally.
It is not flattened into final text.
It is only suppressed when it cannot be represented and would break Claude Code.

## 24.5 No unnecessary feature rejection
Advanced request fields are not rejected merely because the old MVP ignored them.

## 24.6 Loss-minimizing translation
The bridge preserves all representable information from both directions.

## 24.7 Existing runtime quality
The system remains efficient, modular, and provider-agnostic.

## 24.8 No product creep
No auth/rate-limit/multi-tenant/product logic is added.

---

# 25. Explicit implementation instructions for Codex

Use the current repository as the starting point.

You must:
- refactor the current MVP-oriented code into a production-grade transparent protocol bridge
- preserve the existing good structure where possible
- remove text-only and stream-only assumptions
- support structured Anthropic content blocks and event deltas
- support stream and non-stream paths
- keep the core provider-agnostic and model-agnostic
- keep OpenRouter as the first adapter
- preserve Claude Code functionality rather than narrowing it
- implement loss-minimizing translation
- suppress only truly non-representable client-breaking provider constructs

You must not:
- re-scope the project back to MVP
- degrade behavior to text-only
- drop tools/thinking by default
- add auth/rate-limit/product concerns
- silently ignore semantically relevant fields

---

# 26. Concrete deliverables

Produce:

1. updated implementation across the existing codebase
2. updated schemas and domain model
3. updated OpenRouter adapter with structured translation
4. updated SSE encoder supporting multiple block/delta types
5. non-stream response support
6. updated config for compatibility modes and capabilities
7. expanded tests
8. updated README reflecting transparent bridge behavior
9. migration notes from old MVP behavior to V2 behavior

---

# 27. Suggested migration steps

Implement in this order:

## Phase 1
- enrich domain models and ports
- preserve backward compatibility where practical

## Phase 2
- refactor request schemas and API validation
- support full request richness

## Phase 3
- refactor OpenRouter adapter into structured parser/normalizer
- add canonical event mapping

## Phase 4
- refactor SSE encoder to support full block/delta coverage
- add non-stream encoder

## Phase 5
- wire transparent / compat modes
- update tests
- update docs

---

# 28. Final engineering principle

The bridge exists to make Claude Code believe it is speaking to a valid Anthropic-compatible endpoint, while upstream is OpenRouter.

Therefore the correct engineering target is:

- **protocol fidelity**
- **behavior preservation**
- **minimal loss**
- **client stability**
- **no unnecessary policy**

Anything less is not acceptable for V2.