# Phase 1: Direct Anthropic Provider Adapter - Research

**Researched:** 2026-04-14
**Domain:** Anthropic Messages API Direct Integration
**Confidence:** HIGH

## Summary

The Anthropic direct API (`api.anthropic.com`) uses the exact same Messages wire format that this proxy already models in its canonical domain layer. The SSE event types (`message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`, `ping`, `error`) are identical to what OpenRouter proxies — because OpenRouter proxies Anthropic's API. The key structural difference is that **Anthropic's direct API does NOT emit a `[DONE]` sentinel** (removed in version `2023-06-01`), whereas OpenRouter injects `[DONE]` as a compatibility shim. The stream terminates with `event: message_stop` only.

Authentication uses `x-api-key` header (not Bearer token) plus a mandatory `anthropic-version` header. A native `POST /v1/messages/count_tokens` endpoint exists, returning `{"input_tokens": N}` — a clean replacement for the OpenRouter probe hack. The existing `serialization.py` helpers (`usage_from_payload`, `response_from_payload`, `content_block_from_payload`, `delta_from_payload`) are directly reusable since the JSON payload structure is natively Anthropic.

**Primary recommendation:** Build the adapter as a close structural twin of `OpenRouterProvider`, with the main differences being: (1) no `[DONE]` sentinel handling, (2) `x-api-key` + `anthropic-version` headers instead of Bearer auth, (3) native `/v1/messages/count_tokens` endpoint, and (4) optional `anthropic_version` and `anthropic_beta` fields on `ProviderSettings`.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Extract `IncrementalSseParser` and `SseMessage` dataclass into a new shared module `infrastructure/providers/sse.py`. Both OpenRouter and Anthropic adapters import from there.
- **D-02:** Normalizers are forked per provider — `OpenRouterStreamNormalizer` stays in `openrouter.py`, a new `AnthropicStreamNormalizer` is created in `anthropic.py`. They start near-identical and diverge freely as needed.
- **D-03:** End-of-stream sentinel (e.g. `[DONE]` for OpenRouter, `event: message_stop` for Anthropic) is handled inside each provider's normalizer, not in the shared SSE parser.

### Claude's Discretion
- **Provider Settings structure**: `ProviderSettings` currently has `app_name`/`app_url` fields that are OpenRouter-specific. Anthropic needs `anthropic-version` and `anthropic-beta` headers. The agent may choose between optional fields, extra dict, or provider-specific subclasses — whichever fits the existing codebase pattern best.
- **Count Tokens strategy**: Anthropic has a native `/v1/messages/count_tokens` endpoint. The agent should use the native endpoint rather than the OpenRouter-style probe hack.
- **Auth headers**: Anthropic uses `x-api-key` (not Bearer token) plus `anthropic-version` header. The agent decides how to structure the header construction (dedicated method, config fields, or constants).

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.

</user_constraints>

---

## 1. Anthropic Messages API Wire Format

### SSE Event Flow [VERIFIED: platform.claude.com/docs/en/api/messages-streaming]

The stream follows this exact sequence:

1. `message_start` → contains a `Message` object with empty `content`
2. Series of content blocks, each with:
   - `content_block_start` (with `index` and `content_block`)
   - One or more `content_block_delta` events
   - `content_block_stop`
3. One or more `message_delta` events (stop_reason, usage)
4. `message_stop` (terminal event, **no data payload beyond `{"type": "message_stop"}`**)

Interspersed: `ping` events and potentially `error` events.

### Event Payloads

#### `message_start`
```json
{
  "type": "message_start",
  "message": {
    "id": "msg_1nZdL29xx5MUA1yADyHTEsnR8uuvGzszyY",
    "type": "message",
    "role": "assistant",
    "content": [],
    "model": "claude-opus-4-6",
    "stop_reason": null,
    "stop_sequence": null,
    "usage": {"input_tokens": 25, "output_tokens": 1}
  }
}
```

**Note:** When prompt caching is active, `usage` in `message_start` includes `cache_creation_input_tokens` and `cache_read_input_tokens`:
```json
"usage": {
  "input_tokens": 2679,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0,
  "output_tokens": 3
}
```

#### `content_block_start` (text)
```json
{"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}
```

#### `content_block_start` (tool_use)
```json
{"type": "content_block_start", "index": 1, "content_block": {"type": "tool_use", "id": "toolu_01T1x...", "name": "get_weather", "input": {}}}
```

#### `content_block_start` (thinking)
```json
{"type": "content_block_start", "index": 0, "content_block": {"type": "thinking", "thinking": "", "signature": ""}}
```

#### `content_block_delta` (text_delta)
```json
{"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hello"}}
```

#### `content_block_delta` (input_json_delta)
```json
{"type": "content_block_delta", "index": 1, "delta": {"type": "input_json_delta", "partial_json": "{\"location\":"}}
```

#### `content_block_delta` (thinking_delta)
```json
{"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "I need to find..."}}
```

#### `content_block_delta` (signature_delta)
```json
{"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "EqQBCgIYAhIM..."}}
```

#### `content_block_stop`
```json
{"type": "content_block_stop", "index": 0}
```

#### `message_delta`
```json
{"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": null}, "usage": {"output_tokens": 15}}
```

With caching active, `message_delta` usage includes full cache fields:
```json
"usage": {
  "input_tokens": 10682,
  "cache_creation_input_tokens": 0,
  "cache_read_input_tokens": 0,
  "output_tokens": 510,
  "server_tool_use": {"web_search_requests": 1}
}
```

#### `message_stop`
```json
{"type": "message_stop"}
```

#### `ping`
```json
{"type": "ping"}
```

#### `error` (in-stream)
```json
{"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
```

### Critical Difference: No `[DONE]` Sentinel

The Anthropic API version `2023-06-01` explicitly **removed** `data: [DONE]` from the event stream. [VERIFIED: platform.claude.com/docs/en/api/versioning — changelog states "Removed unnecessary `data: [DONE]` event"]. The stream terminates cleanly with `event: message_stop`.

This is the primary behavioral difference from OpenRouter, which injects a `[DONE]` sentinel after the Anthropic events. Per **D-03**, this is handled in the normalizer.

### Compatibility with Existing Domain Model

All event types map 1:1 to existing `CanonicalEvent` variants:

| SSE Event | Domain Model |
|-----------|-------------|
| `message_start` | `MessageStartEvent` |
| `content_block_start` | `ContentBlockStartEvent` |
| `content_block_delta` | `ContentBlockDeltaEvent` |
| `content_block_stop` | `ContentBlockStopEvent` |
| `message_delta` | `MessageDeltaEvent` |
| `message_stop` | `MessageStopEvent` |
| `ping` | `PingEvent` |
| `error` | `ErrorEvent` |

All delta types map to existing `ContentDelta` variants: `TextDelta`, `InputJsonDelta`, `ThinkingDelta`, `SignatureDelta`. No new domain types are needed.

---

## 2. Authentication & Headers

### Required Headers [VERIFIED: platform.claude.com/docs/en/api/getting-started]

| Header | Value | Required |
|--------|-------|----------|
| `x-api-key` | API key string (NOT `Bearer` prefix) | Yes |
| `anthropic-version` | `2023-06-01` | Yes |
| `content-type` | `application/json` | Yes |

### anthropic-version

The only stable version is `2023-06-01`. [VERIFIED: platform.claude.com/docs/en/api/versioning] There is no newer GA version. The version header is mandatory on every request.

### anthropic-beta (Optional)

Format: comma-separated feature names, each following `feature-name-YYYY-MM-DD` pattern. [VERIFIED: platform.claude.com/docs/en/api/beta-headers]

Current known beta strings:
- `files-api-2025-04-14` — Files API
- `managed-agents-2026-04-01` — Managed Agents endpoints

**Key insight:** Prompt caching and extended thinking are now **GA** — no beta header required. The features that originally required beta headers (`prompt-caching-2024-07-31`, `max-tokens-3-5-sonnet-2024-07-15`) have been promoted to stable.

### Response Headers

| Header | Purpose |
|--------|---------|
| `request-id` | Unique request identifier for debugging |
| `anthropic-organization-id` | Organization ID for the API key |

### Rate Limit Headers [ASSUMED]

Standard rate limit response headers include `retry-after` on 429 responses. The proxy doesn't need to parse these — httpx/domain errors already handle rate limiting via `ProviderHttpError` with `upstream_status=429`.

### Header Construction Recommendation

Use a dedicated `_headers()` method on `AnthropicProvider` (mirroring `OpenRouterProvider._headers()`):

```python
def _headers(self, *, accept: str, provider_context: ProviderRequestContext | None = None) -> dict[str, str]:
    headers = {
        "x-api-key": self._settings.api_key.get_secret_value(),
        "anthropic-version": self._settings.anthropic_version,
        "Accept": accept,
        "Content-Type": "application/json",
    }
    if self._settings.anthropic_beta:
        headers["anthropic-beta"] = self._settings.anthropic_beta
    if provider_context is not None:
        headers.update(provider_context.headers)
    return headers
```

---

## 3. Count Tokens Endpoint

### `POST /v1/messages/count_tokens` [VERIFIED: platform.claude.com/docs/en/api/messages/count_tokens]

**Request body:**
```json
{
  "messages": [{"content": "string", "role": "user"}],
  "model": "claude-opus-4-6",
  "system": "optional system prompt",
  "tools": [],
  "tool_choice": {"type": "auto"},
  "thinking": {"type": "enabled", "budget_tokens": 16000}
}
```

**Response:**
```json
{"input_tokens": 2095}
```

### Key Differences from OpenRouter Probe

| Aspect | OpenRouter Probe | Anthropic Native |
|--------|-----------------|------------------|
| Endpoint | `POST /v1/messages` (real completion, max_tokens=1) | `POST /v1/messages/count_tokens` (dedicated) |
| Cost | Uses real tokens (output=1+ tokens) | Free — no output tokens consumed |
| Accuracy | Approximation (probe may behave differently) | Exact count |
| Thinking | Must strip thinking (probe budget conflict) | Supports thinking config |
| Payload | Modified completion request | Purpose-built subset |

### Implementation

The `AnthropicTranslator` needs a `to_count_tokens_payload()` method that builds a clean request for this endpoint. It should include `messages`, `model`, `system`, `tools`, `tool_choice`, and `thinking` — but NOT `stream`, `max_tokens`, `temperature`, `stop_sequences`, or `top_p` (they are not accepted by this endpoint).

The provider's `count_tokens()` method hits `{base_url}/count_tokens` (NOT `/messages/count_tokens` — the base_url will already include `/v1/messages`) and parses `input_tokens` from the JSON response.

**Wait — URL construction note:** If `base_url` is set to `https://api.anthropic.com/v1/messages` (matching OpenRouter's pattern where base_url points to the messages path), then count_tokens URL would be constructed differently. Need to consider this:
- Option A: `base_url = https://api.anthropic.com/v1` → messages at `{base_url}/messages`, count_tokens at `{base_url}/messages/count_tokens`
- Option B: `base_url = https://api.anthropic.com/v1/messages` → messages at `{base_url}`, count_tokens at `{base_url}/count_tokens`

Looking at OpenRouter: `base_url = https://openrouter.ai/api/v1` and `_messages_url()` appends `/messages`. **Recommendation:** Follow the same pattern — `base_url = https://api.anthropic.com/v1` and build URLs as `{base_url}/messages` and `{base_url}/messages/count_tokens`.

---

## 4. ProviderSettings Extension Strategy

### Current State

`ProviderSettings` uses `extra="forbid"` and is a flat Pydantic model. It has three OpenRouter-specific fields:
- `app_name: str = "claude-proxy"` — harmless default, ignored by Anthropic
- `app_url: str | None = None` — harmless default, ignored by Anthropic
- `debug_echo_upstream_body: bool = False` — harmless default, ignored by Anthropic

Anthropic needs:
- `anthropic_version: str` — mandatory, stable default `"2023-06-01"`
- `anthropic_beta: str | None` — optional, comma-separated beta features

### Options Analyzed

| Approach | Pros | Cons |
|----------|------|------|
| **A) Optional fields with defaults** | Simple, KISS, no model hierarchy, all validated by Pydantic | Slight model bloat — each provider ignores some fields |
| B) Discriminated union / subclass | Clean separation per provider | Over-engineering for 2-3 provider-specific fields; breaks `extra="forbid"` pattern; complex YAML schema |
| C) Extra dict (`provider_extra: dict[str, Any]`) | Flexible, no model changes | No validation, no IDE support, violates `extra="forbid"` philosophy |

### Recommendation: Option A — Optional Fields with Defaults

Add two optional fields to `ProviderSettings`:

```python
class ProviderSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # ... existing fields ...
    app_name: str = "claude-proxy"
    app_url: str | None = None
    debug_echo_upstream_body: bool = False
    # Anthropic-specific (ignored by OpenRouter)
    anthropic_version: str = "2023-06-01"
    anthropic_beta: str | None = None
```

**Why this is right:**
- `extra="forbid"` still catches typos — users must explicitly add fields
- OpenRouter config doesn't need to declare `anthropic_version` (it gets the default and ignores it)
- Anthropic config gets validation on both fields
- YAML is straightforward — just add the fields you need
- No model hierarchy to maintain
- Follows KISS
- Scales to 3-4 providers with 2-3 provider-specific fields each before needing a rethink

---

## 5. SSE Parser Extraction Plan

### What Moves to `infrastructure/providers/sse.py`

Per **D-01**, extract:

| Component | Current Location | New Location |
|-----------|-----------------|-------------|
| `SseMessage` dataclass | `openrouter.py` lines 55-57 | `sse.py` |
| `IncrementalSseParser` class | `openrouter.py` lines 60-96 | `sse.py` |

### What Stays

| Component | Location | Reason |
|-----------|----------|--------|
| `OpenRouterStreamNormalizer` | `openrouter.py` | Per D-02 |
| `OpenRouterTranslator` | `openrouter.py` | Provider-specific |
| `OpenRouterProvider` | `openrouter.py` | Provider-specific |
| Helper functions (`_mapping`, `_int_or_default`, etc.) | `openrouter.py` | Used only by OpenRouter normalizer |

### New File: `claude_proxy/infrastructure/providers/sse.py`

```python
from __future__ import annotations

import codecs
from collections.abc import AsyncIterator
from dataclasses import dataclass

from claude_proxy.domain.errors import ProviderProtocolError


@dataclass(slots=True, frozen=True)
class SseMessage:
    event: str | None
    data: str


class IncrementalSseParser:
    async def parse(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[SseMessage]:
        # ... exact existing logic, unchanged ...
```

### Import Changes Required

**`openrouter.py`:** Replace local definitions with:
```python
from claude_proxy.infrastructure.providers.sse import IncrementalSseParser, SseMessage
```

**`test_openrouter_adapter.py`:** Update import:
```python
from claude_proxy.infrastructure.providers.sse import IncrementalSseParser, SseMessage
# Remove from openrouter import
```

**`anthropic.py`:** Import from shared module:
```python
from claude_proxy.infrastructure.providers.sse import IncrementalSseParser, SseMessage
```

### Re-export Consideration

For backward compatibility (in case any external code imports from `openrouter`), keep re-exports in `openrouter.py`:
```python
from claude_proxy.infrastructure.providers.sse import IncrementalSseParser, SseMessage  # re-export
```
This is optional — only needed if external code exists. Internal tests should update imports directly.

---

## 6. Response Differences (Direct vs OpenRouter)

### Fields Anthropic Direct Includes That OpenRouter May Not

| Field | Where | Anthropic Direct | OpenRouter |
|-------|-------|-----------------|------------|
| `cache_creation_input_tokens` | `usage` in `message_start` and `message_delta` | Present when caching active | May not be present |
| `cache_read_input_tokens` | `usage` in `message_start` and `message_delta` | Present when caching active | May not be present |
| `server_tool_use` | `usage` in `message_delta` | Present with server tools (web_search) | Not applicable |

**Good news:** The existing `Usage` model already has `cache_creation_input_tokens` and `cache_read_input_tokens` fields, and `usage_from_payload()` already parses them. Unknown fields (like `server_tool_use`) are captured in `Usage.extra`. **No domain model changes required.**

### Stream Termination

| Provider | End-of-stream | Normalizer Behavior |
|----------|--------------|-------------------|
| OpenRouter | `data: [DONE]` OR `event: message_stop` (both may appear) | Handle both; emit single `MessageStopEvent` |
| Anthropic Direct | `event: message_stop` only | Handle only `message_stop`; `[DONE]` never appears |

The OpenRouter normalizer already has deduplication logic (`_emit_message_stop_once()`) because both `[DONE]` and `message_stop` can arrive. The Anthropic normalizer is simpler — only `message_stop` triggers the stop event.

### Extended Thinking

Anthropic direct streaming with thinking includes the same `thinking_delta` and `signature_delta` events that OpenRouter proxies. No difference in structure. The `message_start` event with thinking **does not include usage** (usage appears only in `message_delta`):
```json
{"type": "message_start", "message": {"id": "msg_01...", ..., "stop_reason": null, "stop_sequence": null}}
```
Note: absent `usage` field in message_start for thinking requests — `usage_from_payload(None)` returns `Usage()` with all `None` fields, which is already handled correctly.

### Content Block Types

Anthropic direct may return content block types not seen through OpenRouter:
- `server_tool_use` — server-side tool invocations (web_search, web_fetch)
- `web_search_tool_result` — search results

These are handled by the existing `content_block_from_payload(strict=False)` which returns `UnknownBlock` for unrecognized types. **No special handling needed in the normalizer.**

---

## 7. Error Response Format

### HTTP Error Responses [VERIFIED: platform.claude.com/docs/en/api/errors]

**Shape:**
```json
{
  "type": "error",
  "error": {
    "type": "not_found_error",
    "message": "The requested resource could not be found."
  },
  "request_id": "req_011CSHoEeqs5C35K2UUqR7Fy"
}
```

### HTTP Status Codes → Error Types

| Status | Error Type | Domain Mapping |
|--------|-----------|----------------|
| 400 | `invalid_request_error` | `ProviderHttpError` (upstream_status=400) |
| 401 | `authentication_error` | `ProviderAuthError` |
| 402 | `billing_error` | `ProviderHttpError` (upstream_status=402) |
| 403 | `permission_error` | `ProviderAuthError` |
| 404 | `not_found_error` | `ProviderHttpError` (upstream_status=404) |
| 413 | `request_too_large` | `ProviderHttpError` (upstream_status=413) |
| 429 | `rate_limit_error` | `ProviderHttpError` (upstream_status=429) |
| 500 | `api_error` | `ProviderHttpError` (upstream_status=500) |
| 504 | `timeout_error` | `UpstreamTimeoutError` |
| 529 | `overloaded_error` | `ProviderHttpError` (upstream_status=529) |

### Error Mapping Implementation

Follow the `_raise_openrouter_http_error()` pattern but for Anthropic:

```python
def _raise_anthropic_http_error(status: int, body: bytes) -> None:
    message = _provider_error_message(body)
    if status in {401, 403}:
        raise ProviderAuthError(
            message or "Anthropic authentication failed",
            details={"provider": "anthropic", "upstream_status": status},
        )
    raise ProviderHttpError(
        message or f"Anthropic returned HTTP {status}",
        upstream_status=status,
        provider="anthropic",
    )
```

The `_provider_error_message()` helper extracts `.error.message` from the JSON body — this works for Anthropic's error shape (`{"type": "error", "error": {"type": "...", "message": "..."}}`) because it checks for `error.message` first. No changes needed.

### In-Stream Errors

Anthropic can send error events mid-stream (e.g., `overloaded_error` during high traffic):
```
event: error
data: {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}
```

The normalizer maps `event_type == "error"` to `ErrorEvent`, matching the existing OpenRouter normalizer pattern.

---

## 8. Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (latest) |
| Config file | `pyproject.toml` [ASSUMED] |
| Quick run command | `pytest tests/unit/test_anthropic_adapter.py -x` |
| Full suite command | `pytest` |

### Required Tests

| Test | Type | Purpose |
|------|------|---------|
| `test_translator_maps_full_request_payload` | unit | Verify `AnthropicTranslator.to_payload()` produces correct Anthropic request JSON |
| `test_translator_maps_count_tokens_payload` | unit | Verify `to_count_tokens_payload()` includes correct fields, excludes stream/max_tokens/temperature |
| `test_stream_normalizer_basic_text` | unit | Parse message_start → content_block_start → delta → stop → message_delta → message_stop |
| `test_stream_normalizer_tool_use` | unit | Parse tool_use content blocks with input_json_delta |
| `test_stream_normalizer_thinking` | unit | Parse thinking blocks with thinking_delta + signature_delta |
| `test_stream_normalizer_no_done_sentinel` | unit | Verify no `[DONE]` handling — only `message_stop` terminates stream |
| `test_stream_normalizer_error_event` | unit | Parse in-stream error events |
| `test_stream_normalizer_ping` | unit | Ping events pass through |
| `test_stream_normalizer_cache_usage` | unit | Verify cache_creation_input_tokens and cache_read_input_tokens in usage |
| `test_headers_construction` | unit | Verify x-api-key, anthropic-version, optional anthropic-beta |
| `test_provider_stream_integration` | integration | Full stream with mocked httpx transport |
| `test_provider_complete_integration` | integration | Non-stream completion with mocked transport |
| `test_provider_count_tokens_integration` | integration | Native count_tokens with mocked transport |
| `test_provider_http_error_mapping` | integration | Status 401/403 → ProviderAuthError, others → ProviderHttpError |
| `test_provider_timeout_mapping` | integration | httpx.TimeoutException → UpstreamTimeoutError |
| `test_sse_parser_extraction` | unit | Verify IncrementalSseParser works from new sse.py location |
| `test_openrouter_still_works` | regression | Verify OpenRouter adapter still works after SSE extraction |

### New Test Files

- `tests/unit/test_anthropic_adapter.py` — Translator, normalizer, headers tests
- `tests/integration/test_anthropic_provider.py` — Provider integration with mocked transport

### Test Patterns to Follow

From existing `test_openrouter_adapter.py`:
- Use `chunk_bytes()` from `conftest` to simulate chunked SSE delivery
- Build SSE byte strings manually for known event sequences
- Use `collect_list()` to gather async iterator results
- Helper `_request()` and `_model()` functions for test fixtures

---

## 9. Architecture Patterns

### Recommended File Structure

```
claude_proxy/infrastructure/providers/
├── __init__.py         # build_provider_registry() — add "anthropic" builder
├── sse.py              # NEW: IncrementalSseParser, SseMessage (extracted from openrouter.py)
├── openrouter.py       # OpenRouterTranslator, OpenRouterStreamNormalizer, OpenRouterProvider
└── anthropic.py        # NEW: AnthropicTranslator, AnthropicStreamNormalizer, AnthropicProvider
```

### Class Structure for `anthropic.py`

Following the Provider = Translator + Normalizer + Provider pattern:

1. **`AnthropicTranslator`** — `to_payload()`, `to_count_tokens_payload()`
2. **`AnthropicStreamNormalizer`** — SSE event → CanonicalEvent mapping (no `[DONE]` handling)
3. **`AnthropicProvider`** — HTTP orchestration: `stream()`, `complete()`, `count_tokens()`

### Helper Functions

Module-level helpers (`_mapping`, `_int_or_default`, `_string_or_none`, `_extras`, `_role_or_default`, `_provider_error_message`) — duplicate from openrouter.py into anthropic.py. These are small, stateless, and copying them avoids coupling the two provider modules. If a third provider emerges (Phase 2: OpenAI), a shared `_helpers.py` could be considered — but not now.

---

## 10. Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SSE parsing | Custom byte-level parser | Existing `IncrementalSseParser` (extracted to `sse.py`) | Already handles UTF-8 incremental decoding, comment lines, multi-line data fields, truncation detection |
| Response deserialization | Custom JSON → domain mappers | Existing `serialization.py` functions | `content_block_from_payload`, `delta_from_payload`, `usage_from_payload`, `response_from_payload` work for native Anthropic JSON |
| HTTP client lifecycle | Own `httpx.AsyncClient` creation | `SharedAsyncClientManager` | Connection pooling, shared lifecycle, configurable limits |
| Error hierarchy | New exception classes | Existing `BridgeError` subclasses | `ProviderAuthError`, `ProviderHttpError`, `ProviderProtocolError`, `UpstreamTimeoutError` cover all cases |
| Config validation | Manual config checking | `ProviderSettings` + `Settings.validate_cross_references()` | Automatically validates provider → model references |

---

## 11. Common Pitfalls

### Pitfall 1: Assuming `[DONE]` sentinel exists
**What goes wrong:** Code hangs waiting for `[DONE]` that never arrives, or treats its absence as a truncated stream.
**Why it happens:** OpenRouter injects `[DONE]` but Anthropic direct does not (removed in 2023-06-01).
**How to avoid:** `AnthropicStreamNormalizer` terminates on `message_stop` only. `IncrementalSseParser` raises `ProviderProtocolError("truncated SSE stream")` only on actual truncation (mid-event).
**Warning signs:** Tests pass with `[DONE]` appended but fail without it.

### Pitfall 2: Bearer token instead of x-api-key
**What goes wrong:** 401 authentication error from Anthropic.
**Why it happens:** Muscle memory from OpenAI/OpenRouter `Authorization: Bearer` pattern.
**How to avoid:** `_headers()` uses `x-api-key` header with raw key value, no `Bearer` prefix.

### Pitfall 3: Missing anthropic-version header
**What goes wrong:** Anthropic rejects the request or uses default (potentially breaking) version behavior.
**Why it happens:** Header omitted because it seems optional.
**How to avoid:** `anthropic_version` field on `ProviderSettings` with default `"2023-06-01"`. Always included in headers.

### Pitfall 4: Wrong URL construction for count_tokens
**What goes wrong:** 404 or wrong endpoint hit.
**Why it happens:** Confusion about whether base_url includes `/messages` or not.
**How to avoid:** Standardize `base_url = https://api.anthropic.com/v1` in config. Provider builds URLs: `{base_url}/messages` for completions, `{base_url}/messages/count_tokens` for token counting.

### Pitfall 5: Not handling in-stream errors
**What goes wrong:** Mid-stream `overloaded_error` events are silently ignored, producing incomplete responses.
**Why it happens:** Only HTTP-level errors are caught; SSE-level errors are not mapped.
**How to avoid:** `AnthropicStreamNormalizer` maps `event_type == "error"` to `ErrorEvent`, same as OpenRouter normalizer.

---

## 12. Code Examples

### Anthropic Provider YAML Config

```yaml
providers:
  anthropic:
    enabled: true
    base_url: https://api.anthropic.com/v1
    api_key_env: ANTHROPIC_API_KEY
    connect_timeout_seconds: 10
    read_timeout_seconds: 300
    write_timeout_seconds: 30
    pool_timeout_seconds: 10
    max_connections: 100
    max_keepalive_connections: 20
    anthropic_version: "2023-06-01"
    anthropic_beta: null

models:
  claude-opus-4-6:
    provider: anthropic
    enabled: true
    supports_stream: true
    supports_nonstream: true
    supports_tools: true
    supports_thinking: true
    thinking_passthrough_mode: full
```

### Registration in `build_provider_registry()`

```python
from claude_proxy.infrastructure.providers.anthropic import AnthropicProvider, AnthropicTranslator

builders = {
    "openrouter": lambda ps: OpenRouterProvider(settings=ps, client_manager=client_manager, translator=OpenRouterTranslator()),
    "anthropic": lambda ps: AnthropicProvider(settings=ps, client_manager=client_manager, translator=AnthropicTranslator()),
}
```

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Rate limit headers follow standard patterns (retry-after on 429) | Section 2 | Low — proxy doesn't parse rate limit headers, just maps status codes |
| A2 | `pyproject.toml` contains pytest configuration | Section 8 | Low — test discovery works regardless |
| A3 | Anthropic direct always sends `usage` in `message_delta` for extended thinking requests | Section 6 | Medium — if absent, `usage_from_payload(None)` returns `Usage()` safely |

## Open Questions

1. **`base_url` convention**: Should anthropic config use `base_url: https://api.anthropic.com/v1` (provider builds `/messages` and `/messages/count_tokens` paths) or `base_url: https://api.anthropic.com/v1/messages` (matching OpenRouter's URL-to-messages pattern)?
   - Recommendation: Use `https://api.anthropic.com/v1` since we need two different paths (`/messages` and `/messages/count_tokens`), and a dedicated `_messages_url()` / `_count_tokens_url()` method pair is cleaner than path manipulation from a messages-level base URL.

2. **Should `_provider_error_message()` and `_raise_*_http_error()` be shared?** Both providers parse the same `{"error": {"message": "..."}}` JSON structure.
   - Recommendation: Not now. Copy `_provider_error_message()` to anthropic.py (it's 15 lines). Extracting shared helpers is a Phase 4/5 concern when N providers exist.

## Environment Availability

Step 2.6: SKIPPED (no external dependencies beyond the project's existing Python 3.14 + httpx stack).

## Sources

### Primary (HIGH confidence)
- [platform.claude.com/docs/en/api/messages-streaming](https://platform.claude.com/docs/en/api/messages-streaming) — SSE event types, wire format, full response examples
- [platform.claude.com/docs/en/api/getting-started](https://platform.claude.com/docs/en/api/getting-started) — Authentication headers, API overview
- [platform.claude.com/docs/en/api/messages/count_tokens](https://platform.claude.com/docs/en/api/messages/count_tokens) — Count tokens endpoint specification
- [platform.claude.com/docs/en/api/errors](https://platform.claude.com/docs/en/api/errors) — Error shapes, HTTP status codes, error types
- [platform.claude.com/docs/en/api/versioning](https://platform.claude.com/docs/en/api/versioning) — Version history, `[DONE]` removal confirmation
- [platform.claude.com/docs/en/api/beta-headers](https://platform.claude.com/docs/en/api/beta-headers) — Beta header format and current beta features
- [platform.claude.com/docs/en/build-with-claude/prompt-caching](https://platform.claude.com/docs/en/build-with-claude/prompt-caching) — Cache usage fields in responses

### Codebase (HIGH confidence)
- `claude_proxy/domain/models.py` — `Usage` already has cache fields, `CanonicalEvent` covers all Anthropic SSE events
- `claude_proxy/domain/serialization.py` — `usage_from_payload()` parses cache fields; `response_from_payload()` handles Anthropic JSON
- `claude_proxy/infrastructure/providers/openrouter.py` — Reference implementation, SSE parser, normalizer, provider structure
- `claude_proxy/infrastructure/config.py` — `ProviderSettings` with `extra="forbid"`, `Settings.validate_cross_references()`

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new libraries needed; all existing infrastructure (httpx, Pydantic, serialization) directly applicable
- Architecture: HIGH — provider adapter pattern is well-established; Anthropic is the simplest case (native wire format)
- Pitfalls: HIGH — verified against official docs; key differences (no `[DONE]`, x-api-key auth, version header) are documented
- Wire format: HIGH — verified against official Anthropic streaming documentation with full response examples

**Research date:** 2026-04-14
**Valid until:** 2026-05-14 (stable — Anthropic API versioning is conservative)
