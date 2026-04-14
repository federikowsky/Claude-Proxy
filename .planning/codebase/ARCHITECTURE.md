# ARCHITECTURE.md — System Design & Patterns

## High-Level Pattern

**Hexagonal / Ports-and-Adapters** with explicit layering:

```
Client (Anthropic API)
        │
        ▼
┌─────────────────────────────┐
│  API Layer (FastAPI)         │  ← ingress, schema validation, HTTP concerns
│  api/routes/, api/schemas.py │
└────────────┬────────────────┘
             │ domain ChatRequest
             ▼
┌─────────────────────────────┐
│  Application Layer           │  ← orchestrate use cases, no HTTP knowledge
│  application/services.py     │
│  application/policies.py     │
│  application/request_preparer│
└────────────┬────────────────┘
             │
       ┌─────┴─────────────────┐
       │                       │
       ▼                       ▼
┌─────────────┐     ┌──────────────────────┐
│  Runtime      │     │  Provider Adapter     │
│  Subsystem    │     │  infra/providers/     │
│  (optional)   │     │  openrouter.py        │
└──────┬───────┘     └──────────────────────┘
       │                       │ httpx
       ▼                       ▼
┌───────────────┐     ┌──────────────────────┐
│  Persistence   │     │  Upstream LLM         │
│  SQLite/Memory │     │  (OpenRouter)         │
└───────────────┘     └──────────────────────┘
```

## Domain Layer (`domain/`)

The purest layer — no framework imports:

- **`models.py`**: frozen dataclasses for all domain entities (`ChatRequest`, `ChatResponse`, `Message`, `ContentBlock` variants, `CanonicalEvent` variants, `ToolDefinition`, `Usage`, …)
- **`enums.py`**: `StrEnum`s: `Role`, `CompatibilityMode`, `ToolCategory`, `RuntimeActionType`, `ActionPolicy`
- **`errors.py`**: `BridgeError` hierarchy with HTTP status codes and structured payloads
- **`ports.py`**: `Protocol` definitions (`ModelProvider`, `ModelResolver`, `RequestPreparer`, `ResponseNormalizer`, `SseEncoder`, `ResponseEncoder`)
- **`serialization.py`**: bidirectional serialization between raw JSON dicts and domain objects; schema normalization for tool `input_schema`

## Application Layer (`application/`)

Orchestrates domain objects via ports; no infra dependencies:

- **`services.py`** (`MessageService`): main use-case class — resolves model, prepares request, delegates to runtime or direct provider, encodes response
- **`policies.py`** (`CompatibilityNormalizer`, `StreamEventSequencer`): stream transformation (thinking passthrough, unknown block suppression, stream ordering)
- **`request_preparer.py`** (`ModelAwareRequestPreparer`): validates/strips extension fields, normalizes tool schemas, annotates tool categories
- **`sse.py`** (`AnthropicSseEncoder`, `AnthropicResponseEncoder`): serialize domain events to Anthropic SSE wire format
- **`runtime_contract.py`** (`RuntimeContractEnforcer`): pre-flight contract checks against model capabilities
- **`runtime_actions.py`** (`RuntimeActionClassifier`): classify model tool-use blocks as actions (TOOL_CALL, STATE_TRANSITION, ORCHESTRATION_ACTION, etc.)
- **`tool_classifier.py`** (`ToolClassifier`): thin wrapper delegating to `CapabilityRegistry`

## Capabilities Layer (`capabilities/`)

Registry-driven tool knowledge base — the **semantic contract** layer:

- **`registry.py`** (`CapabilityRegistry`): alias resolution, category lookup, event mapping; singleton via `@lru_cache`
- **`builtins.py`**: 50+ frozen `CapabilityRecord` rows mapping tool names → category, event, schema contract
- **`record.py`** (`CapabilityRecord`): the data row type
- **`enums.py`**: `CapabilityInventoryClass`, `BridgeImplementationStatus`, `SchemaContractKind`, `EvidenceTier`, `TextControlAttemptPolicy`
- **`tool_use_prepare.py`**: outbound normalization/repair of tool inputs before client emission
- **`tool_use_normalize.py`**: per-contract schema repair (`apply_schema_contract`)
- **`signals.py`**: delivery/origin context for multi-signal classification
- **`text_control.py`**: detect plain-text runtime control language in model output
- **`bash_emulation.py`**, **`ordinary_tool_emulation.py`**: emulation detection heuristics
- **`families.py`**, **`coverage_matrix.py`**: capability grouping and coverage reporting

## Runtime Layer (`runtime/`)

Optional stateful session orchestration (enabled via `bridge.runtime_orchestration_enabled: true`):

- **`state.py`**: `RuntimeState` (14 states), `ModeQualifiers` (6 orthogonal mode dimensions), `SessionRuntimeState`
- **`state_machine.py`** (`apply_runtime_transition`): deterministic, policy-driven state transitions for every `RuntimeEventKind`
- **`events.py`**: `RuntimeEventKind` enum (external / model-derived / internal), `RuntimeEvent` dataclass
- **`orchestrator.py`** (`RuntimeOrchestrator`): owns store + log; processes tool blocks in streams; applies transitions
- **`stream.py`** (`runtime_orchestrate_stream`): async generator wrapping a canonical event stream with orchestrator intercepts
- **`classifier.py`** (`RuntimeModelClassifier`): maps model artifacts to `ModelClassification` (event kind + forward decision)
- **`policies.py`** (`RuntimeOrchestrationPolicies`): configurable resolution strategies for ambiguous transitions
- **`recovery.py`**: deterministic session rebuild from persisted event log (checkpoint + tail replay)
- **`invariants.py`** (`assert_runtime_invariants`): hard invariant checks called after every transition
- **`session_store.py`** / **`event_log.py`**: protocols + in-memory implementations
- **`persistence/sqlite_backend.py`** (`SqliteRuntimeStores`): thread-safe SQLite backend

## Infrastructure Layer (`infrastructure/`)

Wires ports to concrete implementations:

- **`config.py`**: `Settings` Pydantic model hierarchy + YAML loading + env override parsing
- **`http.py`** (`SharedAsyncClientManager`): single shared HTTPX async client with dynamic limits
- **`providers/openrouter.py`**: `OpenRouterTranslator` (payload mapping) + `OpenRouterProvider` (HTTP calls, SSE parsing, error translation)
- **`resolvers.py`** (`StaticModelResolver`): maps model name to `ModelInfo` from config
- **`logging.py`**: JSON log formatter setup

## API Layer (`api/`)

FastAPI entry points:

- **`routes/messages.py`**: `POST /v1/messages`, `POST /v1/messages/count_tokens`
- **`routes/health.py`**: `GET /health`
- **`routes/runtime_control.py`**: `GET/POST /v1/runtime/sessions/…` (15+ endpoints)
- **`schemas.py`**: Pydantic request models with `.to_domain()` conversion
- **`dependencies.py`**: FastAPI `Depends` factories (`get_message_service`, `get_runtime_orchestrator`)
- **`errors.py`**: exception handlers mapping `BridgeError` → JSON responses
- **`http_debug.py`**: optional body-preview middleware (enabled by `server.debug`)

## Entry Point

`claude_proxy/main.py` `create_app()`:
1. Loads settings, sets up logging, builds infra objects
2. Constructs `RuntimeOrchestrator` (SQLite or memory) if enabled
3. Builds `MessageService` with all dependencies wired
4. Registers routers and middleware
5. Returns `FastAPI` app

`claude_proxy/__main__.py` calls `uvicorn.run(create_app(), …)` for the CLI entry point.

## Key Data Flow: Streaming Request

```
POST /v1/messages (stream=true)
  → AnthropicMessagesRequest.to_domain() → ChatRequest
  → MessageService.stream()
      → StaticModelResolver.resolve(model) → ModelInfo
      → ModelAwareRequestPreparer.prepare() → normalized ChatRequest
      → [if runtime enabled] runtime_orchestrate_stream()
      → OpenRouterProvider.stream()
          → OpenRouterTranslator.to_payload() → HTTP POST /v1/chat/completions
          → IncrementalSseParser → canonical CanonicalEvent stream
      → CompatibilityNormalizer.normalize_stream() → filtered events
      → StreamEventSequencer
      → AnthropicSseEncoder.encode() → bytes
  → StreamingResponse(text/event-stream)
```

## Dependency Injection Pattern

All objects are constructed in `create_app()` and injected:
- Services stored on `app.state`
- Route handlers receive them via FastAPI `Depends(get_message_service)` etc.
- No global mutable state; all singletons are created once and passed explicitly
