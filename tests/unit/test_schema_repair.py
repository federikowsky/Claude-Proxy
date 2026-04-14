"""Unit tests for generic JSON-Schema-driven tool input repair."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from llm_proxy.capabilities.tool_use_normalize import repair_from_schema
from llm_proxy.capabilities.tool_use_prepare import repair_stream_tool_blocks
from llm_proxy.domain.models import (
    CanonicalEvent,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDelta,
    TextBlock,
    ToolUseBlock,
)
from llm_proxy.runtime.policies import InteractiveInputRepairMode, RuntimeOrchestrationPolicies


# ---------------------------------------------------------------------------
# repair_from_schema unit tests
# ---------------------------------------------------------------------------

_SCHEMA_WITH_REQUIRED_ARRAY = {
    "type": "object",
    "properties": {
        "items": {"type": "array"},
        "label": {"type": "string"},
    },
    "required": ["items", "label"],
}


def test_missing_required_array_backfilled() -> None:
    result, repairs = repair_from_schema({}, _SCHEMA_WITH_REQUIRED_ARRAY)
    assert result == {"items": [], "label": ""}
    assert "items_zero_filled_array" in repairs
    assert "label_zero_filled_string" in repairs


def test_null_required_field_backfilled() -> None:
    result, repairs = repair_from_schema({"items": None, "label": "ok"}, _SCHEMA_WITH_REQUIRED_ARRAY)
    assert result == {"items": [], "label": "ok"}
    assert "items_zero_filled_array" in repairs
    assert len(repairs) == 1


def test_present_values_untouched() -> None:
    inp = {"items": [1, 2], "label": "hello"}
    result, repairs = repair_from_schema(inp, _SCHEMA_WITH_REQUIRED_ARRAY)
    assert result == inp
    assert repairs == []


def test_default_from_schema_used() -> None:
    schema = {
        "type": "object",
        "properties": {"mode": {"type": "string", "default": "auto"}},
        "required": ["mode"],
    }
    result, repairs = repair_from_schema({}, schema)
    assert result == {"mode": "auto"}
    assert "mode_defaulted_from_schema" in repairs


def test_all_type_zero_values() -> None:
    schema = {
        "type": "object",
        "properties": {
            "a": {"type": "array"},
            "o": {"type": "object"},
            "s": {"type": "string"},
            "n": {"type": "number"},
            "i": {"type": "integer"},
            "b": {"type": "boolean"},
        },
        "required": ["a", "o", "s", "n", "i", "b"],
    }
    result, repairs = repair_from_schema({}, schema)
    assert result == {"a": [], "o": {}, "s": "", "n": 0, "i": 0, "b": False}
    assert len(repairs) == 6


def test_non_dict_input_passthrough() -> None:
    result, repairs = repair_from_schema("not a dict", _SCHEMA_WITH_REQUIRED_ARRAY)
    assert result == "not a dict"
    assert repairs == []


def test_no_required_no_repair() -> None:
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    result, repairs = repair_from_schema({}, schema)
    assert result == {}
    assert repairs == []


def test_unknown_type_not_backfilled() -> None:
    schema = {
        "type": "object",
        "properties": {"x": {"type": "customtype"}},
        "required": ["x"],
    }
    result, repairs = repair_from_schema({}, schema)
    assert result == {}
    assert repairs == []


def test_extra_fields_preserved() -> None:
    result, repairs = repair_from_schema(
        {"items": [1], "extra": "keep"},
        _SCHEMA_WITH_REQUIRED_ARRAY,
    )
    assert result["extra"] == "keep"
    assert result["items"] == [1]
    assert "label_zero_filled_string" in repairs


# ---------------------------------------------------------------------------
# Stream integration: generic repair via tool_schemas
# ---------------------------------------------------------------------------

def _policies() -> RuntimeOrchestrationPolicies:
    return RuntimeOrchestrationPolicies(interactive_input_repair=InteractiveInputRepairMode.REPAIR)


async def _from_list(events: list[CanonicalEvent]) -> AsyncIterator[CanonicalEvent]:
    for ev in events:
        yield ev


async def _collect(events: AsyncIterator[CanonicalEvent]) -> list[CanonicalEvent]:
    return [ev async for ev in events]


_MCP_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "limit": {"type": "integer", "default": 10},
    },
    "required": ["query", "limit"],
}


@pytest.mark.asyncio
async def test_stream_generic_repair_mcp_tool_via_deltas() -> None:
    """MCP tool with missing required fields gets repaired via tool_schemas."""
    tool_schemas = {"mcp__search__find": _MCP_SCHEMA}
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="mcp__search__find", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json="{}")),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(
        repair_stream_tool_blocks(_from_list(events), policies=_policies(), tool_schemas=tool_schemas)
    )
    # start + repaired delta + stop
    assert len(result) == 3
    repaired = json.loads(result[1].delta.partial_json)
    assert repaired["query"] == ""
    assert repaired["limit"] == 10  # default from schema


@pytest.mark.asyncio
async def test_stream_generic_repair_anthropic_native_path() -> None:
    """MCP tool with full input in start event, no deltas — repaired in-place."""
    tool_schemas = {"mcp__db__insert": _MCP_SCHEMA}
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="mcp__db__insert", input={"query": None})),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(
        repair_stream_tool_blocks(_from_list(events), policies=_policies(), tool_schemas=tool_schemas)
    )
    assert len(result) == 2
    block = result[0].block
    assert block.input["query"] == ""
    assert block.input["limit"] == 10


@pytest.mark.asyncio
async def test_stream_no_schema_no_repair() -> None:
    """Tool without a schema entry passes through unchanged."""
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="unknown_tool", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"x":1}')),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(
        repair_stream_tool_blocks(_from_list(events), policies=_policies(), tool_schemas={"other": {}})
    )
    # Not buffered, so start passes through immediately, then delta, then stop
    assert len(result) == 3
    assert isinstance(result[0], ContentBlockStartEvent)
    assert result[1].delta.partial_json == '{"x":1}'


@pytest.mark.asyncio
async def test_stream_registry_tool_without_contract_still_gets_generic_schema_repair() -> None:
    """Registry-known generic tools like Read still use request schema fallback repair."""
    tool_schemas = {
        "Read": {
            "type": "object",
            "properties": {
                "file_path": {"type": "string"},
                "offset": {"type": "integer", "default": 1},
            },
            "required": ["file_path"],
        },
    }
    events: list[CanonicalEvent] = [
        ContentBlockStartEvent(index=0, block=ToolUseBlock(id="t1", name="Read", input={})),
        ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json="{}")),
        ContentBlockStopEvent(index=0),
    ]
    result = await _collect(
        repair_stream_tool_blocks(_from_list(events), policies=_policies(), tool_schemas=tool_schemas)
    )
    repaired = json.loads(result[1].delta.partial_json)
    assert repaired["file_path"] == ""
