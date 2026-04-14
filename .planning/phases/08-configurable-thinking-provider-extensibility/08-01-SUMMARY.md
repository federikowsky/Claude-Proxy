---
phase: 08-configurable-thinking-provider-extensibility
plan: 01
status: complete
started: 2026-04-14T12:56:32Z
completed: 2026-04-14T12:59:00Z
---

## What Was Built

Extended the configuration schema and domain model with per-model thinking extraction
configuration and per-provider extensibility fields.

### Key Changes

**ModelSettings** (config.py):
- `thinking_open_tag: str | None = "<think>"` — configurable thinking open tag
- `thinking_close_tag: str | None = "</think>"` — configurable thinking close tag
- `thinking_extraction_fields: tuple[str, ...] = ("reasoning_content", "reasoning")` — configurable delta field names

**ProviderSettings** (config.py):
- `custom_headers: dict[str, str] = {}` — arbitrary HTTP headers per provider
- `finish_reason_map: dict[str, str] | None = None` — override stop_reason mapping

**ModelInfo** (models.py): Matching fields for downstream pipeline consumption.

**StaticModelResolver** (resolvers.py): Maps all new fields from config → domain.

**Validation**: Tag-pair consistency enforced (both set or both null).

### key-files

created:
- (none — all existing files modified)

modified:
- llm_proxy/infrastructure/config.py
- llm_proxy/domain/models.py
- llm_proxy/infrastructure/resolvers.py
- config/llm-proxy.example.yaml
- tests/unit/test_config.py

### Tests

- 11 config tests total (4 existing + 7 new)
- Covers: defaults, custom tags, null tags, mismatched tag validation, custom headers, finish reason map, resolver mapping

### Commits

1. `feat(08-01): add configurable thinking extraction and provider extensibility fields`
2. `test(08-01): config tests and example documentation for new fields`

## Self-Check: PASSED
