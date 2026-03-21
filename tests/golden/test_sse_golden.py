from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from claude_proxy.application.policies import AnthropicSafeStreamNormalizer
from claude_proxy.application.sse import AnthropicSseEncoder
from claude_proxy.domain.enums import ReasoningMode, Role, StreamPolicyName
from claude_proxy.domain.models import ChatMessage, ChatRequest, ModelInfo
from claude_proxy.infrastructure.providers.openrouter import IncrementalSseParser, OpenRouterEventMapper
from tests.conftest import chunk_bytes, collect_bytes


def _request(model: str) -> ChatRequest:
    return ChatRequest(
        model=model,
        messages=(ChatMessage(role=Role.USER, text="Hello"),),
        system=None,
        max_tokens=64,
        temperature=None,
        stream=True,
        metadata=None,
    )


def _model(model: str, reasoning_mode: ReasoningMode) -> ModelInfo:
    return ModelInfo(
        name=model,
        provider="openrouter",
        enabled=True,
        supports_streaming=True,
        supports_text=True,
        supports_tools=False,
        supports_multimodal=False,
        reasoning_mode=reasoning_mode,
    )


async def _provider_events(data: bytes) -> AsyncIterator[object]:
    parser = IncrementalSseParser()
    mapper = OpenRouterEventMapper()

    async def chunks() -> AsyncIterator[bytes]:
        for chunk in chunk_bytes(data, 13):
            yield chunk

    async for message in parser.parse(chunks()):
        event = mapper.map_message(message)
        if event is not None:
            yield event


@pytest.mark.parametrize(
    ("fixture_name", "expected_name", "policy", "model_name", "reasoning_mode"),
    [
        (
            "provider_text.sse",
            "provider_text.expected",
            StreamPolicyName.STRICT,
            "anthropic/claude-sonnet-4",
            ReasoningMode.PROMOTE_IF_EMPTY,
        ),
        (
            "provider_text_reasoning.sse",
            "provider_text_reasoning.expected",
            StreamPolicyName.STRICT,
            "openai/gpt-4.1-mini",
            ReasoningMode.DROP,
        ),
        (
            "provider_reasoning_only.sse",
            "provider_reasoning_only.expected",
            StreamPolicyName.PROMOTE_IF_EMPTY,
            "anthropic/claude-sonnet-4",
            ReasoningMode.PROMOTE_IF_EMPTY,
        ),
        (
            "provider_unknown.sse",
            "provider_unknown.expected",
            StreamPolicyName.STRICT,
            "openai/gpt-4.1-mini",
            ReasoningMode.DROP,
        ),
    ],
)
@pytest.mark.asyncio
async def test_golden_sse_output(
    fixtures_dir: Path,
    fixture_name: str,
    expected_name: str,
    policy: StreamPolicyName,
    model_name: str,
    reasoning_mode: ReasoningMode,
) -> None:
    fixture = (fixtures_dir / fixture_name).read_bytes()
    expected = (fixtures_dir / expected_name).read_bytes()
    normalizer = AnthropicSafeStreamNormalizer(emit_usage=True, max_reasoning_buffer_chars=4096)
    encoder = AnthropicSseEncoder(message_id_factory=lambda: "msg_fixed")
    request = _request(model_name)
    model = _model(model_name, reasoning_mode)

    actual = await collect_bytes(
        encoder.encode(
            normalizer.normalize(
                request,
                model,
                _provider_events(fixture),
                policy,
            ),
        ),
    )

    assert actual == expected

