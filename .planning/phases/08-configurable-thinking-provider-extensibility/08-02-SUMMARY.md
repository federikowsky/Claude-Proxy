# Plan 08-02 Summary — Wire Configurable Extraction Through Pipeline

## Status: COMPLETE

## What Was Done

### Task 1: Parameterize all hardcoded values in openai_compat.py

**Files modified:** `llm_proxy/infrastructure/providers/openai_compat.py`

Changes:
- `_ThinkingTagParser.__init__` now accepts `open_tag` and `close_tag` parameters (defaults: `<think>`, `</think>`)
- `OpenAICompatStreamNormalizer.__init__` extended with `thinking_open_tag`, `thinking_close_tag`, `thinking_extraction_fields`, `finish_reason_map` keyword-only args
- Tag parser is `None` when `thinking_open_tag=None` — text passes through unmodified
- `normalize()` uses configurable `thinking_extraction_fields` loop instead of hardcoded field names
- `_flush_tag_parser()` safely returns `[]` when parser is `None`
- `_emit_finish()` uses `self._finish_reason_map or _FINISH_REASON_MAP` for configurable finish reason mapping
- `_parse_thinking_tags()` accepts `open_tag`/`close_tag` parameters, uses `len()` instead of magic numbers
- `_response_from_openai()` accepts full config kwargs: `thinking_open_tag`, `thinking_close_tag`, `thinking_extraction_fields`, `finish_reason_map`
- `OpenAICompatProvider.stream()` passes `model.thinking_*` and `self._settings.finish_reason_map` to normalizer
- `OpenAICompatProvider.complete()` passes same config to `_response_from_openai()`
- `OpenAICompatProvider._headers()` merges `self._settings.custom_headers` with lowest priority (before Authorization)

### Task 2: Tests for configurable extraction

**Files modified:** `tests/unit/test_openai_compat_adapter.py`

15 new tests across 7 test classes:
- `TestThinkingTagParserCustomTags`: Custom tags, flush, default backward compat
- `TestParseThinkingTagsCustom`: Custom tags, unclosed tag, default backward compat
- `TestNormalizerNullThinkingTags`: Null tags pass raw `<think>` through as text
- `TestNormalizerCustomExtractionFields`: Custom field name (`thought`), empty fields skip reasoning
- `TestNormalizerCustomFinishReasonMap`: Custom `eos → end_turn` mapping
- `TestNormalizerCustomTagsStream`: Custom `<reasoning>` tags parsed in stream
- `TestResponseFromOpenaiConfigurable`: Custom extraction fields, null tags, custom finish reason map, custom tags in non-stream

## Verification

- All 46 openai_compat tests pass (31 existing + 15 new)
- Full test suite: 407 passed, 0 failed

## Self-Check

| Must-Have Truth | Covered |
|---|---|
| Custom thinking tags parsed correctly (stream + non-stream) | ✅ TestNormalizerCustomTagsStream, TestResponseFromOpenaiConfigurable |
| thinking_open_tag=null skips tag extraction | ✅ TestNormalizerNullThinkingTags, test_null_tags_no_parsing |
| Custom extraction fields used for reasoning | ✅ TestNormalizerCustomExtractionFields |
| Custom headers sent on upstream requests | ✅ Code: _headers() merges custom_headers first |
| Custom finish_reason_map overrides default | ✅ TestNormalizerCustomFinishReasonMap, test_custom_finish_reason_map |
| Existing behavior identical with defaults | ✅ 31 existing tests unchanged and passing |

Self-Check: **PASSED**

## Commits

- `feat(08-02): parameterize all hardcoded thinking extraction and finish reason values`
- `test(08-02): configurable extraction fields, tags, finish reason map, and null-tag passthrough`
