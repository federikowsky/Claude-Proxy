# ROADMAP.md

## Milestone 1: Multi-Protocol LLM Proxy

### Phase 1: Direct Anthropic Provider Adapter ✅
**Status:** Complete
**Goal:** Native Anthropic API adapter alongside the existing OpenRouter adapter.
- Extracted SSE parser to shared `infrastructure/providers/sse.py` module
- `AnthropicProvider` with x-api-key auth, native `/messages/count_tokens`
- Extended `ProviderSettings` with `anthropic_version`, `anthropic_beta`
- 22 tests (12 unit + 10 integration)
Depends on: —
**Requirements:** [R-02]
**Plans:** 3 plans
Plans:
- [x] 01-01-PLAN.md — SSE Parser Extraction + ProviderSettings Extension
- [x] 01-02-PLAN.md — Anthropic Provider Adapter Implementation
- [x] 01-03-PLAN.md — Anthropic Adapter Unit + Integration Tests

### Phase 2: OpenAI-Compatible Provider Framework ✅
**Status:** Complete
**Goal:** Generic OpenAI Chat Completions upstream adapter framework with NVIDIA NIM and Gemini providers.
- `OpenAICompatProvider` with Bearer auth, probe-based count_tokens
- `OpenAICompatTranslator` (Anthropic canonical → OpenAI Chat Completions payload)
- `OpenAICompatStreamNormalizer` (OpenAI SSE → Anthropic canonical events)
- Registered NVIDIA NIM and Gemini as providers via the framework
- 30 tests (17 unit + 13 integration)
Depends on: —
**Requirements:** [R-02, R-04]
**Plans:** — (executed inline)

### Phase 3: Project Rename
**Goal:** Rename claude-proxy → llm-proxy across the entire codebase.
- Package directory: `claude_proxy/` → `llm_proxy/`
- `pyproject.toml`: name, packages, entry point, description
- All imports across source and test files (~92 .py files)
- Config files: `claude-proxy*.yaml` → `llm-proxy*.yaml`
- Environment variable prefix: `CLAUDE_PROXY__` → `LLM_PROXY__`
- Config path env var: `CLAUDE_PROXY_CONFIG` → `LLM_PROXY_CONFIG`
- README and documentation references
- Verify all 312+ tests pass under new package name
Depends on: Phase 2
**Requirements:** [R-07]
**Plans:** 1 plan
Plans:
- [ ] 03-01-PLAN.md — Full Project Rename (claude-proxy → llm-proxy)

### Phase 4: OpenAI Direct Provider
**Goal:** Register OpenAI as a first-class provider using the existing OpenAI-compatible adapter framework.
- Add `"openai"` builder in `build_provider_registry()` using `OpenAICompatProvider`
- Config block: `base_url: https://api.openai.com/v1`, `api_key_env: OPENAI_API_KEY`
- Sample model entries: `gpt-4.1`, `o3`, `o4-mini`
- Unit + integration tests for OpenAI-specific behavior
Depends on: Phase 3
**Requirements:** [R-02, R-04]

### Phase 5: OpenAI Chat Completions Ingress & Egress
**Goal:** Accept OpenAI-format requests and return OpenAI-format responses, enabling Codex CLI and any OpenAI-compatible client.
- New route: `POST /v1/chat/completions` (streaming + non-streaming)
- Pydantic request schema for OpenAI Chat Completions format
- Ingress translator: OpenAI Chat Completions request → domain `ChatRequest`
- Egress encoder: `ChatResponse` → OpenAI JSON, `CanonicalEvent` → OpenAI SSE
- Reuse existing `MessageService` for provider dispatch
- Internal canonical model unchanged (Anthropic-based)
Depends on: Phase 3
**Requirements:** [R-01, R-03, R-05, R-06]

### Phase 6: Cross-Protocol Integration Tests & Golden Fixtures
**Goal:** Full coverage of multi-provider, multi-ingress flows.
- Golden tests: each provider SSE → canonical → each egress format
- Integration tests: Anthropic ingress → OpenAI provider → Anthropic response
- Integration tests: OpenAI ingress → Anthropic provider → OpenAI response
- Cross-provider model routing tests
- Regression: all existing tests pass unchanged
Depends on: Phase 4, Phase 5
**Requirements:** [R-05, R-06, R-07]

### Phase 7: Production Hardening & Release Preparation
**Goal:** Production-ready quality across the entire proxy.
- Error model audit: verify HTTP status mapping for all error paths across all providers and ingress protocols
- Config validation: all model→provider references resolve at startup, schema-level checks
- Structured logging audit: consistent log format, appropriate levels, no sensitive data leaks
- Health check enhancements: provider connectivity status
- Performance: connection pool tuning, timeout documentation
- Documentation: complete README, config reference, architecture guide, changelog
Depends on: Phase 6
**Requirements:** [R-07]
