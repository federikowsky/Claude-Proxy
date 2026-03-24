# Migration Notes V2

## What changed

- The bridge is no longer MVP-only.
- Requests are no longer restricted to text-only content.
- `POST /v1/messages` now supports both streaming and non-streaming responses.
- The internal domain model is now canonical and structured.
- OpenRouter responses are normalized into canonical content blocks and stream events before Anthropic encoding.
- Compatibility modes are explicit:
  - `transparent`
  - `compat`
  - `debug`

## Removed V1 assumptions

- no single-text-block SSE encoder
- no blanket reasoning dropping by default
- no forced `stream=true`
- no request reduction to plain text

## Operational config change

The old `stream.policy` section is replaced by:

```yaml
bridge:
  compatibility_mode: transparent
  emit_usage: true
  passthrough_request_fields: []
```
