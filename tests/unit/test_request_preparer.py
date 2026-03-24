"""Unit tests for ModelAwareRequestPreparer schema normalization and provider invariant."""
from __future__ import annotations

import logging

import pytest

from claude_proxy.application.request_preparer import ModelAwareRequestPreparer
from claude_proxy.domain.enums import ActionPolicy, Role, ThinkingPassthroughMode
from claude_proxy.domain.errors import ProviderBoundaryError, RequestValidationError
from claude_proxy.domain.models import ChatRequest, Message, ModelInfo, ToolDefinition


def _model(
    *,
    name: str = "test/model",
    unsupported_request_fields: tuple[str, ...] = (),
) -> ModelInfo:
    return ModelInfo(
        name=name,
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=False,
        thinking_passthrough_mode=ThinkingPassthroughMode.OFF,
        unsupported_request_fields=unsupported_request_fields,
    )


def _request(*, tools: tuple[ToolDefinition, ...] = (), extensions: dict = {}) -> ChatRequest:
    return ChatRequest(
        model="test/model",
        messages=(Message(role=Role.USER, content=()),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=tools,
        tool_choice=None,
        thinking=None,
        stream=False,
        extensions=extensions,
    )


def _tool(name: str, schema: object) -> ToolDefinition:
    return ToolDefinition(name=name, description=None, input_schema=schema)  # type: ignore[arg-type]


class TestRequestPreparerSchemaScenarios:
    preparer = ModelAwareRequestPreparer(allowed_request_fields=("output_config",))

    def test_missing_schema_normalised_to_object(self) -> None:
        # Empty dict {} simulates a missing/empty schema — must be normalised to object schema.
        tool = ToolDefinition(name="bash", description=None, input_schema={})
        request = _request(tools=(tool,))
        prepared = self.preparer.prepare(request, _model())
        assert prepared.tools[0].input_schema.get("type") == "object"
        assert prepared.tools[0].input_schema.get("properties") == {}


    def test_object_schema_without_properties_gets_properties(self) -> None:
        tool = _tool("bash", {"type": "object"})
        request = _request(tools=(tool,))
        prepared = self.preparer.prepare(request, _model())
        assert prepared.tools[0].input_schema["properties"] == {}

    def test_well_formed_schema_identity_preserved(self) -> None:
        tool = _tool("bash", {"type": "object", "properties": {"cmd": {"type": "string"}}})
        request = _request(tools=(tool,))
        prepared = self.preparer.prepare(request, _model())
        # If schema was already fine, the request object itself may differ due to category
        # annotation, but schema content is the same.
        assert prepared.tools[0].input_schema["type"] == "object"
        assert "cmd" in prepared.tools[0].input_schema["properties"]

    def test_no_tools_request_returns_identity(self) -> None:
        request = _request(tools=())
        prepared = self.preparer.prepare(request, _model())
        assert prepared is request

    def test_tool_category_annotated(self) -> None:
        from claude_proxy.domain.enums import ToolCategory

        tool = _tool("bash", {"type": "object", "properties": {}})
        request = _request(tools=(tool,))
        prepared = self.preparer.prepare(request, _model())
        assert prepared.tools[0].category is ToolCategory.GENERIC

    def test_extension_field_stripping_still_works(self) -> None:
        request = _request(extensions={"output_config": {"format": "json"}})
        prepared = self.preparer.prepare(
            request,
            _model(unsupported_request_fields=("output_config",)),
        )
        assert "output_config" not in prepared.extensions

    def test_unknown_extension_field_raises(self) -> None:
        request = _request(extensions={"bad_field": 1})
        with pytest.raises(RequestValidationError):
            self.preparer.prepare(request, _model())


class TestRequestPreparerProviderBoundaryInvariant:
    """The boundary invariant check runs after normalisation. It should be very hard to
    trigger in practice — it would require the normaliser to produce an empty schema,
    which it currently cannot do.  We test it by sub-classing to inject a mock."""

    def test_invariant_raises_for_empty_dict_schema(self) -> None:
        """Verify the guard logic itself by calling _assert_schema_invariant directly."""
        from claude_proxy.domain.enums import ToolCategory
        from dataclasses import replace

        tool = ToolDefinition(
            name="broken_tool",
            description=None,
            input_schema={},  # Empty — violates invariant
            category=ToolCategory.ORDINARY,
        )
        with pytest.raises(ProviderBoundaryError) as exc_info:
            ModelAwareRequestPreparer._assert_schema_invariant((tool,))
        assert "broken_tool" in str(exc_info.value)

    def test_invariant_passes_for_valid_schema(self) -> None:
        from claude_proxy.domain.enums import ToolCategory

        tool = ToolDefinition(
            name="good_tool",
            description=None,
            input_schema={"type": "object", "properties": {}},
            category=ToolCategory.ORDINARY,
        )
        # Must not raise
        ModelAwareRequestPreparer._assert_schema_invariant((tool,))


class TestRequestPreparerLogging:
    def test_schema_repair_logged(self, caplog: pytest.LogCaptureFixture) -> None:
        preparer = ModelAwareRequestPreparer()
        tool = _tool("bash", {"type": "object"})  # missing properties
        request = _request(tools=(tool,))
        with caplog.at_level(logging.DEBUG, logger="claude_proxy.serialization"):
            preparer.prepare(request, _model())
        assert any("schema_properties_injected" in r.getMessage() for r in caplog.records)
