from __future__ import annotations

from collections.abc import AsyncIterator

import pytest

from claude_proxy.application.policies import AnthropicSafeStreamNormalizer
from claude_proxy.domain.enums import ReasoningMode, StreamPolicyName
from claude_proxy.domain.models import (
    ChatRequest,
    MessageStopEvent,
    ModelInfo,
    RawReasoningDelta,
    RawStop,
    RawTextDelta,
    RawUsage,
    TextDeltaEvent,
    Usage,
    UsageEvent,
)
from claude_proxy.domain.enums import Role
from claude_proxy.domain.models import ChatMessage
from tests.conftest import collect_list


def _request() -> ChatRequest:
    return ChatRequest(
        model="anthropic/claude-sonnet-4",
        messages=(ChatMessage(role=Role.USER, text="Hello"),),
        system=None,
        max_tokens=32,
        temperature=None,
        stream=True,
        metadata=None,
    )


def _model() -> ModelInfo:
    return ModelInfo(
        name="anthropic/claude-sonnet-4",
        provider="openrouter",
        enabled=True,
        supports_streaming=True,
        supports_text=True,
        supports_tools=False,
        supports_multimodal=False,
        reasoning_mode=ReasoningMode.PROMOTE_IF_EMPTY,
    )


async def _strict_events() -> AsyncIterator[object]:
    yield RawReasoningDelta(text="hidden")
    yield RawTextDelta(text="visible")
    yield RawUsage(usage=Usage(input_tokens=1, output_tokens=2))
    yield RawStop(stop_reason="end_turn")


async def _reasoning_only_events() -> AsyncIterator[object]:
    yield RawReasoningDelta(text="promoted")
    yield RawStop(stop_reason="end_turn")


@pytest.mark.asyncio
async def test_normalizer_strict_drops_reasoning() -> None:
    normalizer = AnthropicSafeStreamNormalizer(emit_usage=True, max_reasoning_buffer_chars=64)
    events = await collect_list(
        normalizer.normalize(
            _request(),
            _model(),
            _strict_events(),
            StreamPolicyName.STRICT,
        ),
    )

    assert TextDeltaEvent(text="visible") in events
    assert TextDeltaEvent(text="hidden") not in events
    assert UsageEvent(usage=Usage(input_tokens=1, output_tokens=2)) in events
    assert MessageStopEvent(stop_reason="end_turn") in events


@pytest.mark.asyncio
async def test_normalizer_promotes_reasoning_when_text_is_empty() -> None:
    normalizer = AnthropicSafeStreamNormalizer(emit_usage=False, max_reasoning_buffer_chars=64)
    events = await collect_list(
        normalizer.normalize(
            _request(),
            _model(),
            _reasoning_only_events(),
            StreamPolicyName.PROMOTE_IF_EMPTY,
        ),
    )

    assert TextDeltaEvent(text="promoted") in events

