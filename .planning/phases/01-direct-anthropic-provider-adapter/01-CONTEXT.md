# Phase 1: Direct Anthropic Provider Adapter - Context

**Gathered:** 2026-04-14
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a native Anthropic API adapter (`api.anthropic.com`) alongside the existing OpenRouter adapter. The new adapter implements the `ModelProvider` Protocol and plugs into the existing provider registry. Anthropic-native SSE parsing, auth, and config. Unit + integration tests with mocked transport.

</domain>

<decisions>
## Implementation Decisions

### SSE Parser & Normalizer Architecture
- **D-01:** Extract `IncrementalSseParser` and `SseMessage` dataclass into a new shared module `infrastructure/providers/sse.py`. Both OpenRouter and Anthropic adapters import from there.
- **D-02:** Normalizers are forked per provider — `OpenRouterStreamNormalizer` stays in `openrouter.py`, a new `AnthropicStreamNormalizer` is created in `anthropic.py`. They start near-identical and diverge freely as needed.
- **D-03:** End-of-stream sentinel (e.g. `[DONE]` for OpenRouter, `event: message_stop` for Anthropic) is handled inside each provider's normalizer, not in the shared SSE parser.

### Agent's Discretion
- **Provider Settings structure**: `ProviderSettings` currently has `app_name`/`app_url` fields that are OpenRouter-specific. Anthropic needs `anthropic-version` and `anthropic-beta` headers. The agent may choose between optional fields, extra dict, or provider-specific subclasses — whichever fits the existing codebase pattern best.
- **Count Tokens strategy**: Anthropic has a native `/v1/messages/count_tokens` endpoint. The agent should use the native endpoint rather than the OpenRouter-style probe hack.
- **Auth headers**: Anthropic uses `x-api-key` (not Bearer token) plus `anthropic-version` header. The agent decides how to structure the header construction (dedicated method, config fields, or constants).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Domain Contracts
- `claude_proxy/domain/ports.py` — `ModelProvider` Protocol that the adapter must implement (stream, complete, count_tokens)
- `claude_proxy/domain/models.py` — All canonical event types (CanonicalEvent variants), ChatRequest, ChatResponse, ModelInfo, ProviderRequestContext
- `claude_proxy/domain/errors.py` — BridgeError hierarchy (ProviderAuthError, ProviderBoundaryError, ProviderHttpError, ProviderProtocolError, UpstreamTimeoutError)

### Reference Implementation
- `claude_proxy/infrastructure/providers/openrouter.py` — Full template: Translator + StreamNormalizer + Provider class + error handling + SSE parser
- `claude_proxy/infrastructure/providers/__init__.py` — `build_provider_registry()` where the new adapter must be registered

### Serialization Layer
- `claude_proxy/domain/serialization.py` — `content_block_from_payload()`, `delta_from_payload()`, `response_from_payload()`, `usage_from_payload()` — reusable for Anthropic response parsing

### Configuration
- `claude_proxy/infrastructure/config.py` — `ProviderSettings`, `ModelSettings`, `Settings` with cross-reference validation
- `config/claude-proxy.yaml` — Live config template

### Conventions
- `.planning/codebase/CONVENTIONS.md` — Coding patterns, naming, error handling, async patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `IncrementalSseParser`: Generic SSE parser (bytes→SseMessage) — will be extracted to shared module
- `serialization.py` functions: `content_block_from_payload()`, `delta_from_payload()`, `response_from_payload()`, `usage_from_payload()` — directly applicable to Anthropic JSON responses
- `SharedAsyncClientManager`: Shared httpx async client with configurable limits — reused for Anthropic HTTP calls
- `ProviderSettings` Pydantic model: base_url, api_key_env, timeouts — works for Anthropic with minor additions

### Established Patterns
- Provider structure: Translator (payload mapping) + StreamNormalizer (SSE→canonical) + Provider class (HTTP orchestration)
- Error mapping: httpx exceptions → domain BridgeError subclasses
- Frozen dataclasses for all domain objects; `dataclasses.replace()` for mutations
- Module-level `_logger = logging.getLogger("claude_proxy.<subsystem>")`

### Integration Points
- `build_provider_registry()` in `providers/__init__.py` — add `"anthropic"` builder
- `config.py` `Settings.validate_cross_references()` — automatic; new provider just needs matching models in config
- `config/claude-proxy.yaml` — add `anthropic` provider block + model entries

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches following the OpenRouter adapter as a structural template.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 01-direct-anthropic-provider-adapter*
*Context gathered: 2026-04-14*
