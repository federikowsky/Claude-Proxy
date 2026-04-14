# REQUIREMENTS.md

## Milestone: Dual-Provider Architecture

### R-01: Dual-protocol ingress
- `POST /v1/messages` (Anthropic Messages API) — **existing**
- `POST /v1/chat/completions` (OpenAI Chat Completions API) — **new**
- `POST /v1/messages/count_tokens` — **existing**
- `POST /v1/chat/completions/count_tokens` — **new**

### R-02: Multi-provider upstream
- OpenRouter adapter — **existing**
- Direct Anthropic API adapter — **new**
- Direct OpenAI API adapter — **new**
- Provider selection via model routing config

### R-03: Canonical Anthropic-compatible output
- All responses (stream + non-stream) normalized to Anthropic Messages wire format
- Regardless of which upstream provider was used
- Regardless of which ingress protocol the client used

### R-04: Model support
- Claude models (via Anthropic direct or OpenRouter)
- OpenAI models — GPT-4.1, o3, o4-mini, Codex (via OpenAI direct or OpenRouter)
- Model-aware request preparation and field stripping per provider

### R-05: Streaming end-to-end
- SSE Anthropic-compatible output for all providers
- Incremental SSE parsing for all upstream protocols
- Content block sequencing (max one open block at a time)

### R-06: Token counting dual-protocol
- `/v1/messages/count_tokens` (Anthropic ingress) — **existing**
- `/v1/chat/completions/count_tokens` (OpenAI ingress) — **new**
- Both delegate to appropriate provider token counting endpoint

### Out of Scope (MVP)
- Multimodal content (images, audio)
- Tool-calling server-side execution
- Waterfall protocols
- Authentication / authorization
- Multi-tenancy
