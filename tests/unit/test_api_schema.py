from __future__ import annotations

import pytest
from pydantic import ValidationError

from llm_proxy.api.schemas import AnthropicCountTokensRequest, AnthropicMessagesRequest
from llm_proxy.domain.models import TextBlock, ToolResultBlock


def test_request_schema_preserves_structured_blocks_tools_and_thinking() -> None:
    payload = AnthropicMessagesRequest.model_validate(
        {
            "model": "anthropic/claude-sonnet-4",
            "messages": [
                {"role": "user", "content": "Run diagnostics"},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": "toolu_1",
                            "content": [{"type": "text", "text": "done"}],
                        },
                    ],
                },
            ],
            "system": [{"type": "text", "text": "You are a bridge."}],
            "metadata": {"session_id": "abc"},
            "temperature": 0.2,
            "top_p": 0.9,
            "max_tokens": 256,
            "stop_sequences": ["</done>"],
            "stream": False,
            "tools": [
                {
                    "name": "bash",
                    "description": "Run shell commands",
                    "input_schema": {"type": "object"},
                },
            ],
            "tool_choice": {"type": "auto"},
            "thinking": {"type": "enabled", "budget_tokens": 128},
            "context_management": {"workspace": "repo"},
        },
    )

    request = payload.to_domain()
    assert request.stream is False
    assert request.system == (TextBlock(text="You are a bridge."),)
    assert isinstance(request.messages[1].content[0], ToolResultBlock)
    assert request.tools[0].name == "bash"
    assert request.tool_choice is not None and request.tool_choice.type == "auto"
    assert request.thinking is not None and request.thinking.budget_tokens == 128
    assert request.extensions["context_management"] == {"workspace": "repo"}


def test_request_schema_rejects_invalid_content_block_shape() -> None:
    with pytest.raises(ValidationError):
        AnthropicMessagesRequest.model_validate(
            {
                "model": "anthropic/claude-sonnet-4",
                "messages": [{"role": "user", "content": [{"text": "missing type"}]}],
                "max_tokens": 32,
                "stream": True,
            },
        )


def test_count_tokens_schema_builds_nonstream_probe_request() -> None:
    payload = AnthropicCountTokensRequest.model_validate(
        {
            "model": "anthropic/claude-sonnet-4",
            "messages": [{"role": "user", "content": "Count this"}],
            "tools": [{"name": "bash", "input_schema": {"type": "object"}}],
            "thinking": {"type": "enabled", "budget_tokens": 2048},
            "context_management": {"workspace": "repo"},
        },
    )

    request = payload.to_domain()
    assert request.stream is False
    assert request.max_tokens == 1
    assert request.thinking is not None and request.thinking.budget_tokens == 2048
    assert request.extensions["context_management"] == {"workspace": "repo"}


def test_request_schema_missing_tool_input_schema_defaults_to_object_schema() -> None:
    payload = AnthropicMessagesRequest.model_validate(
        {
            "model": "anthropic/claude-sonnet-4",
            "messages": [{"role": "user", "content": "search web"}],
            "max_tokens": 32,
            "stream": True,
            "tools": [{"name": "WebSearch", "description": "Search web"}],
        },
    )

    request = payload.to_domain()
    assert request.tools[0].input_schema == {"type": "object", "properties": {}}
