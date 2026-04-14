# Phase 4: OpenAI Direct Provider - Context

**Gathered:** 2025-07-23
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase — discuss skipped)

<domain>
## Phase Boundary

Register OpenAI as a first-class provider using the existing OpenAI-compatible adapter framework (`OpenAICompatProvider`). Add `"openai"` builder in `build_provider_registry()`, config block, sample model entries, and tests.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at the agent's discretion — pure infrastructure phase. Use ROADMAP phase goal, existing `openai_compat.py` patterns, and codebase conventions to guide decisions.

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `llm_proxy/infrastructure/providers/openai_compat.py` — `OpenAICompatProvider`, `OpenAICompatTranslator`, `OpenAICompatStreamNormalizer`
- `llm_proxy/infrastructure/providers/__init__.py` — `build_provider_registry()` with nvidia/gemini builders as template
- `tests/unit/test_openai_compat_adapter.py` — existing tests as template
- `tests/integration/test_openai_compat_provider.py` — existing integration tests as template

### Established Patterns
- Provider builder: lambda in `builders` dict, receives `provider_settings`, returns `ModelProvider`
- Config: provider block in YAML with `base_url`, `api_key_env`, `enabled`
- Registration: `OpenAICompatProvider(settings, client_manager, translator=OpenAICompatTranslator("name"), provider_name="name")`

### Integration Points
- `llm_proxy/infrastructure/providers/__init__.py` — add "openai" builder
- `config/llm-proxy.yaml`, `config/llm-proxy.example.yaml`, `config/llm-proxy-test.yaml` — add openai provider block
- Models config: add sample OpenAI model entries

</code_context>

<specifics>
## Specific Ideas

No specific requirements — infrastructure phase. Follow the nvidia/gemini pattern exactly.

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>
