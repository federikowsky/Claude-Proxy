# ROADMAP.md

## Milestone 1: Dual-Provider Architecture

### Phase 1: Direct Anthropic Provider Adapter
**Goal:** Add a native Anthropic API adapter alongside the existing OpenRouter adapter.
- New `infrastructure/providers/anthropic.py` implementing `ModelProvider` protocol
- Anthropic-native SSE parsing (different wire format from OpenRouter/OpenAI)
- Auth via `ANTHROPIC_API_KEY` env var
- Config: new provider block in YAML with connect/read/write timeouts
- Register in `build_provider_registry()`
- Unit + integration tests with mocked transport
Depends on: —
Canonical refs: `domain/ports.py`, `infrastructure/providers/openrouter.py`

### Phase 2: Direct OpenAI Provider Adapter
**Goal:** Add a native OpenAI API adapter for direct GPT/Codex access.
- New `infrastructure/providers/openai.py` implementing `ModelProvider` protocol
- OpenAI Chat Completions SSE parsing → canonical events
- OpenAI-to-Anthropic content normalization (roles, content blocks, tool_use mapping)
- Auth via `OPENAI_API_KEY` env var
- Model-aware differences: thinking support, stop reasons, usage mapping
- Unit + integration tests
Depends on: —
Canonical refs: `domain/ports.py`, `infrastructure/providers/openrouter.py`

### Phase 3: OpenAI Chat Completions Ingress
**Goal:** Accept OpenAI-format requests on `/v1/chat/completions` and `/v1/chat/completions/count_tokens`.
- New route + Pydantic request schema for OpenAI Chat Completions format
- Conversion layer: OpenAI request → domain `ChatRequest`
- Reuse existing `MessageService` for the actual provider call
- Response encoding: domain `ChatResponse` / `CanonicalEvent` → OpenAI-format JSON/SSE
- All responses remain Anthropic-canonical internally; only the egress differs if client expects OpenAI format
Depends on: Phase 1 or Phase 2 (at least one new provider to test against)
Canonical refs: `api/schemas.py`, `api/routes/messages.py`, `application/sse.py`

### Phase 4: Provider Registry & Routing Refactor
**Goal:** Generalize the provider registry and model routing for N providers.
- Refactor `build_provider_registry()` to be data-driven (no hardcoded builder map)
- Model → provider mapping from config (already partially in place)
- Fallback chain: primary provider → fallback provider per model
- Provider health awareness (optional): mark provider as degraded on repeated errors
- Config validation: all model→provider references resolve
Depends on: Phase 1, Phase 2
Canonical refs: `infrastructure/providers/__init__.py`, `infrastructure/config.py`, `infrastructure/resolvers.py`

### Phase 5: Request Preparation Generalization
**Goal:** Make request preparation truly provider-agnostic.
- Factor out OpenRouter-specific payload construction
- Each provider adapter owns its own `to_payload()` and `from_response()`
- Common pre-flight: schema normalization, field stripping, tool classification (already exists)
- Provider-specific pre-flight: header injection, auth, model name format
- Ensure `ModelAwareRequestPreparer` works identically regardless of target provider
Depends on: Phase 1, Phase 2, Phase 4
Canonical refs: `application/request_preparer.py`, `domain/serialization.py`

### Phase 6: Integration Testing & Golden Tests
**Goal:** Full coverage of dual-provider, dual-ingress flows.
- Golden tests: Anthropic provider SSE → canonical → Anthropic SSE
- Golden tests: OpenAI provider SSE → canonical → Anthropic SSE  
- Golden tests: OpenAI ingress → canonical → response
- Integration tests: cross-provider fallback
- Integration tests: mixed-provider model routing
- Regression: all existing tests pass unchanged
Depends on: Phase 1, Phase 2, Phase 3, Phase 4, Phase 5
Canonical refs: `tests/fixtures/`, `tests/golden/`, `tests/integration/`
