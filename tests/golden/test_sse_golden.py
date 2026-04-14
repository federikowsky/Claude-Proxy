from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from claude_proxy.application.policies import CompatibilityNormalizer, StreamEventSequencer
from claude_proxy.application.sse import AnthropicSseEncoder
from claude_proxy.domain.enums import CompatibilityMode
from claude_proxy.domain.models import ChatRequest, Message, ModelInfo
from claude_proxy.domain.enums import Role
from claude_proxy.infrastructure.providers.openrouter import OpenRouterStreamNormalizer
from claude_proxy.infrastructure.providers.sse import IncrementalSseParser
from tests.conftest import chunk_bytes, collect_bytes


def _request(model: str) -> ChatRequest:
    return ChatRequest(
        model=model,
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
        stream=True,
    )


def _model(model: str) -> ModelInfo:
    return ModelInfo(
        name=model,
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
    )


async def _provider_events(data: bytes) -> AsyncIterator[object]:
    parser = IncrementalSseParser()
    normalizer = OpenRouterStreamNormalizer()

    async def chunks() -> AsyncIterator[bytes]:
        for chunk in chunk_bytes(data, 17):
            yield chunk

    async for message in parser.parse(chunks()):
        event = normalizer.normalize(message)
        if event is not None:
            yield event


@pytest.mark.parametrize(
    ("fixture_name", "expected_name", "mode", "model_name"),
    [
        ("provider_text.sse", "provider_text.expected", CompatibilityMode.TRANSPARENT, "anthropic/claude-sonnet-4"),
        (
            "provider_text_reasoning.sse",
            "provider_text_reasoning.expected",
            CompatibilityMode.TRANSPARENT,
            "anthropic/claude-sonnet-4",
        ),
        (
            "provider_reasoning_only.sse",
            "provider_reasoning_only.expected",
            CompatibilityMode.COMPAT,
            "anthropic/claude-sonnet-4",
        ),
        ("provider_tool_use.sse", "provider_tool_use.expected", CompatibilityMode.TRANSPARENT, "anthropic/claude-sonnet-4"),
        ("provider_unknown.sse", "provider_unknown.expected", CompatibilityMode.TRANSPARENT, "anthropic/claude-sonnet-4"),
    ],
)
@pytest.mark.asyncio
async def test_golden_sse_output(
    fixtures_dir: Path,
    fixture_name: str,
    expected_name: str,
    mode: CompatibilityMode,
    model_name: str,
) -> None:
    fixture = (fixtures_dir / fixture_name).read_bytes()
    expected = (fixtures_dir / expected_name).read_bytes()
    compatibility = CompatibilityNormalizer()
    sequencer = StreamEventSequencer()
    encoder = AnthropicSseEncoder()

    actual = await collect_bytes(
        encoder.encode(
            sequencer.sequence(
                compatibility.normalize_stream(
                    _request(model_name),
                    _model(model_name),
                    _provider_events(fixture),
                    mode,
                ),
            ),
        ),
    )

    assert actual == expected
