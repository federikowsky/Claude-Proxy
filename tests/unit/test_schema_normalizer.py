"""Unit tests for the tool schema normalizer (domain/serialization.py)."""
from __future__ import annotations

import logging

import pytest

from llm_proxy.domain.serialization import normalize_tool_schema


class TestNormalizeToolSchemaMissingOrInvalid:
    def test_none_returns_fallback_object_schema(self) -> None:
        result = normalize_tool_schema(None, tool_name="my_tool")
        assert result == {"type": "object", "properties": {}}

    def test_non_mapping_string_returns_fallback(self) -> None:
        result = normalize_tool_schema("not a mapping")
        assert result == {"type": "object", "properties": {}}

    def test_non_mapping_list_returns_fallback(self) -> None:
        result = normalize_tool_schema(["a", "b"])
        assert result == {"type": "object", "properties": {}}

    def test_non_mapping_int_returns_fallback(self) -> None:
        result = normalize_tool_schema(42)
        assert result == {"type": "object", "properties": {}}

    def test_empty_mapping_returns_fallback(self) -> None:
        result = normalize_tool_schema({})
        assert result == {"type": "object", "properties": {}}

    def test_missing_schema_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="llm_proxy.serialization"):
            normalize_tool_schema(None, tool_name="tool_x")
        assert any("schema_missing" in r.getMessage() for r in caplog.records)

    def test_invalid_type_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="llm_proxy.serialization"):
            normalize_tool_schema("bad", tool_name="tool_x")
        assert any("schema_invalid_type" in r.getMessage() for r in caplog.records)

    def test_empty_mapping_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="llm_proxy.serialization"):
            normalize_tool_schema({}, tool_name="tool_y")
        assert any("schema_empty" in r.getMessage() for r in caplog.records)


class TestNormalizeToolSchemaObjectNormalization:
    def test_object_without_properties_gets_empty_properties_injected(self) -> None:
        result = normalize_tool_schema({"type": "object"})
        assert result["type"] == "object"
        assert result["properties"] == {}

    def test_object_with_properties_unchanged(self) -> None:
        schema = {"type": "object", "properties": {"cmd": {"type": "string"}}}
        result = normalize_tool_schema(schema)
        assert result["properties"] == {"cmd": {"type": "string"}}

    def test_object_like_hint_without_type_gets_type_injected(self) -> None:
        result = normalize_tool_schema({"properties": {"a": {"type": "string"}}})
        assert result["type"] == "object"
        assert result["properties"] == {"a": {"type": "string"}}

    def test_required_not_list_is_stripped(self) -> None:
        result = normalize_tool_schema({"type": "object", "properties": {}, "required": "cmd"})
        assert "required" not in result

    def test_required_list_with_non_string_items_filtered(self) -> None:
        result = normalize_tool_schema({"type": "object", "properties": {}, "required": ["a", 2, "b", None]})
        assert result["required"] == ["a", "b"]

    def test_required_list_all_strings_unchanged(self) -> None:
        result = normalize_tool_schema({"type": "object", "properties": {}, "required": ["a", "b"]})
        assert result["required"] == ["a", "b"]

    def test_required_empty_list_preserved(self) -> None:
        result = normalize_tool_schema({"type": "object", "properties": {}, "required": []})
        assert result["required"] == []

    def test_extra_keys_preserved(self) -> None:
        result = normalize_tool_schema({"type": "object", "properties": {}, "additionalProperties": False})
        assert result["additionalProperties"] is False

    def test_properties_injection_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="llm_proxy.serialization"):
            normalize_tool_schema({"type": "object"}, tool_name="my_tool")
        assert any("schema_properties_injected" in r.getMessage() for r in caplog.records)

    def test_type_injection_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.DEBUG, logger="llm_proxy.serialization"):
            normalize_tool_schema({"properties": {}}, tool_name="t")
        assert any("schema_type_injected" in r.getMessage() for r in caplog.records)


class TestNormalizeToolSchemaIdentityAndNonObjectTypes:
    def test_non_object_type_string_schema_returned_as_copy(self) -> None:
        schema = {"type": "string"}
        result = normalize_tool_schema(schema)
        assert result == {"type": "string"}

    def test_returns_dict_not_original_mapping(self) -> None:
        from collections.abc import Mapping as ABCMapping

        schema = {"type": "object", "properties": {"x": {"type": "integer"}}, "required": ["x"]}
        result = normalize_tool_schema(schema)
        # Must be a plain dict
        assert type(result) is dict  # noqa: E721
        # Must not be the same object (always a copy)
        assert result is not schema

    def test_well_formed_schema_returned_unchanged_content(self) -> None:
        schema = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]}
        result = normalize_tool_schema(schema)
        assert result == schema
