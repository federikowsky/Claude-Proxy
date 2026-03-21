from __future__ import annotations

import pytest
from pydantic import ValidationError

from claude_proxy.api.schemas import AnthropicMessagesRequest
from claude_proxy.domain.enums import Role


def test_request_schema_supports_text_blocks() -> None:
    payload = AnthropicMessagesRequest.model_validate(
        {
            "model": "openai/gpt-4.1-mini",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": " world"},
                    ],
                },
            ],
            "system": [{"type": "text", "text": "You are concise."}],
            "max_tokens": 32,
            "stream": True,
        },
    )

    domain = payload.to_domain()
    assert domain.messages[0].role is Role.USER
    assert domain.messages[0].text == "Hello world"
    assert domain.system == "You are concise."


def test_request_schema_rejects_non_stream_requests() -> None:
    with pytest.raises(ValidationError):
        AnthropicMessagesRequest.model_validate(
            {
                "model": "openai/gpt-4.1-mini",
                "messages": [{"role": "user", "content": "Hello"}],
                "max_tokens": 32,
                "stream": False,
            },
        )


def test_request_schema_rejects_non_text_content() -> None:
    with pytest.raises(ValidationError):
        AnthropicMessagesRequest.model_validate(
            {
                "model": "openai/gpt-4.1-mini",
                "messages": [
                    {
                        "role": "user",
                        "content": [{"type": "image", "source": {"type": "base64"}}],
                    },
                ],
                "max_tokens": 32,
                "stream": True,
            },
        )

