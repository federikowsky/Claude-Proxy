from __future__ import annotations

import logging

import pytest

from claude_proxy.application.request_preparer import ModelAwareRequestPreparer
from claude_proxy.domain.enums import Role
from claude_proxy.domain.errors import RequestValidationError
from claude_proxy.domain.models import ChatRequest, Message, ModelInfo


def _request(*, extensions: dict[str, object]) -> ChatRequest:
    return ChatRequest(
        model="anthropic/claude-sonnet-4",
        messages=(Message(role=Role.USER, content=()),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=(),
        tool_choice=None,
        thinking=None,
        stream=False,
        extensions=extensions,
    )


def _model(
    *,
    name: str = "anthropic/claude-sonnet-4",
    unsupported_request_fields: tuple[str, ...] = (),
) -> ModelInfo:
    return ModelInfo(
        name=name,
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
        unsupported_request_fields=unsupported_request_fields,
    )


def test_request_preparer_rejects_unknown_extension_fields() -> None:
    preparer = ModelAwareRequestPreparer(allowed_request_fields=("output_config",))

    with pytest.raises(RequestValidationError):
        preparer.prepare(
            _request(extensions={"context_management": {"cwd": "."}}),
            _model(),
        )


def test_request_preparer_strips_unsupported_fields_for_target_model(
    caplog: pytest.LogCaptureFixture,
) -> None:
    preparer = ModelAwareRequestPreparer(allowed_request_fields=("output_config",))

    with caplog.at_level(logging.DEBUG, logger="claude_proxy.request"):
        prepared = preparer.prepare(
            _request(extensions={"output_config": {"format": "json"}}),
            _model(
                name="stepfun/step-3.5-flash:free",
                unsupported_request_fields=("output_config",),
            ),
        )

    assert prepared.extensions == {}
    assert any(
        "request_fields_stripped model=stepfun/step-3.5-flash:free fields=output_config" in record.getMessage()
        for record in caplog.records
    )


def test_request_preparer_preserves_supported_fields_for_target_model() -> None:
    preparer = ModelAwareRequestPreparer(allowed_request_fields=("output_config",))
    prepared = preparer.prepare(
        _request(extensions={"output_config": {"format": "json"}}),
        _model(),
    )

    assert prepared.extensions == {"output_config": {"format": "json"}}
