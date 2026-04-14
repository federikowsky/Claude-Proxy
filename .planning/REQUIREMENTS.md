# REQUIREMENTS.md

## Milestone: Multi-Protocol LLM Proxy

### R-01: Dual-protocol ingress
- `POST /v1/messages` (Anthropic Messages API) — **existing**
- `POST /v1/chat/completions` (OpenAI Chat Completions API) — **new**
- `POST /v1/messages/count_tokens` — **existing**
- `GET /health` — **existing**

### R-02: Multi-provider upstream
- OpenRouter adapter — **complete**
- Direct Anthropic API adapter — **complete**
- Direct OpenAI API adapter — **new** (uses existing OpenAI-compatible framework)
- NVIDIA NIM adapter — **complete**
- Gemini adapter — **complete**
- Provider selection via model routing config

### R-03: Bidirectional protocol translation
- Internal canonical model: Anthropic Messages format
- Anthropic ingress → canonical → provider → canonical → Anthropic egress
- OpenAI ingress → canonical → provider → canonical → OpenAI egress
- Provider wire protocol is independent of client protocol

### R-04: Model support
- Claude models (via Anthropic direct or OpenRouter)
- GPT / o-series models (via OpenAI direct or OpenRouter)
- NVIDIA NIM models (via NVIDIA direct)
- Gemini models (via Gemini direct)
- Model-aware request preparation and field stripping per provider

### R-05: Streaming end-to-end
- SSE output for both Anthropic and OpenAI response formats
- Incremental SSE parsing for all upstream protocols
- Content block sequencing (max one open block at a time)

### R-06: Token counting
- `/v1/messages/count_tokens` (Anthropic ingress) — **existing**
- Native endpoint (Anthropic) or probe-based (OpenRouter, OpenAI, NVIDIA, Gemini)

### R-07: Production quality
- Comprehensive test suite (unit + integration + golden)
- Error model with proper HTTP status mapping across all providers and ingress protocols
- Structured logging with consistent format
- Configuration validation at startup
- Health check endpoint
- Complete documentation and config reference

### Out of Scope (V1)
- Multimodal content (images, audio)
- Server-side tool execution
- Authentication / authorization
- Multi-tenancy
