"""Unit tests for OpenAI direct provider registration and translator behavior."""

from __future__ import annotations

import pytest

from llm_proxy.domain.enums import Role
from llm_proxy.domain.models import (
    ChatRequest,
    Message,
    ModelInfo,
    TextBlock,
)
from llm_proxy.infrastructure.providers.openai_compat import OpenAICompatTranslator


def _request(*, stream: bool = True) -> ChatRequest:
    return ChatRequest(
        model="gpt-4.1",
        messages=(
            Message(role=Role.USER, content=(TextBlock(text="Hello"),)),
        ),
        system=(TextBlock(text="You are helpful."),),
        metadata=None,
        temperature=0.7,
        top_p=None,
        max_tokens=256,
        stop_sequences=(),
        tools=(),
        tool_choice=None,
        thinking=None,
        stream=stream,
        extensions={},
    )


def _model(*, name: str = "gpt-4.1") -> ModelInfo:
    return ModelInfo(
        name=name,
        provider="openai",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
    )


class TestOpenAITranslator:
    def test_payload_model_passthrough(self) -> None:
        translator = OpenAICompatTranslator("openai")
        payload = translator.to_payload(_request(), _model())
        assert payload["model"] == "gpt-4.1"

    def test_payload_system_message_first(self) -> None:
        translator = OpenAICompatTranslator("openai")
        payload = translator.to_payload(_request(), _model())
        messages = payload["messages"]
        assert messages[0] == {"role": "system", "content": "You are helpful."}
        assert messages[1]["role"] == "user"

    def test_payload_stream_options(self) -> None:
        translator = OpenAICompatTranslator("openai")
        payload = translator.to_payload(_request(stream=True), _model())
        assert payload["stream"] is True
        assert payload["stream_options"] == {"include_usage": True}

    def test_payload_non_stream(self) -> None:
        translator = OpenAICompatTranslator("openai")
        payload = translator.to_payload(_request(stream=False), _model())
        assert payload["stream"] is False
        assert "stream_options" not in payload

    def test_payload_max_tokens(self) -> None:
        translator = OpenAICompatTranslator("openai")
        payload = translator.to_payload(_request(), _model())
        assert payload["max_tokens"] == 256

    def test_o_series_model_passthrough(self) -> None:
        translator = OpenAICompatTranslator("openai")
        req = ChatRequest(
            model="o3",
            messages=(Message(role=Role.USER, content=(TextBlock(text="Hi"),)),),
            system=None,
            metadata=None,
            temperature=None,
            top_p=None,
            max_tokens=1024,
            stop_sequences=(),
            tools=(),
            tool_choice=None,
            thinking=None,
            stream=True,
            extensions={},
        )
        model = _model(name="o3")
        payload = translator.to_payload(req, model)
        assert payload["model"] == "o3"
        assert payload["max_tokens"] == 1024
