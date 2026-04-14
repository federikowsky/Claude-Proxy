"""Cross-protocol golden tests.

Verify the full pipeline: provider SSE → canonical events → OpenAI egress.
Tests both Anthropic and OpenAI egress from the same provider fixtures.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from llm_proxy.application.openai_egress import OpenAIResponseEncoder, OpenAISseEncoder
from llm_proxy.application.policies import CompatibilityNormalizer, StreamEventSequencer
from llm_proxy.application.sse import AnthropicSseEncoder
from llm_proxy.domain.enums import CompatibilityMode, Role
from llm_proxy.domain.models import ChatRequest, Message, ModelInfo
from llm_proxy.infrastructure.providers.openrouter import OpenRouterStreamNormalizer
from llm_proxy.infrastructure.providers.sse import IncrementalSseParser
from tests.conftest import chunk_bytes, collect_bytes


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _model(model: str, provider: str = "openrouter") -> ModelInfo:
    return ModelInfo(
        name=model,
        provider=provider,
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


async def _canonical_stream(fixture: bytes, model_name: str):
    """Run fixture through provider → normalize → sequence pipeline."""
    compatibility = CompatibilityNormalizer()
    sequencer = StreamEventSequencer()
    return sequencer.sequence(
        compatibility.normalize_stream(
            _request(model_name),
            _model(model_name),
            _provider_events(fixture),
            CompatibilityMode.TRANSPARENT,
        ),
    )


def _parse_openai_frames(raw: bytes) -> list[dict | str]:
    """Parse OpenAI SSE output into list of parsed data frames."""
    frames = []
    for line in raw.decode("utf-8").split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            payload = line[len("data: "):]
            if payload == "[DONE]":
                frames.append("[DONE]")
            else:
                frames.append(json.loads(payload))
    return frames


def _parse_anthropic_frames(raw: bytes) -> list[dict]:
    """Parse Anthropic SSE output into list of parsed data frames."""
    frames = []
    for line in raw.decode("utf-8").split("\n"):
        line = line.strip()
        if line.startswith("data: "):
            frames.append(json.loads(line[len("data: "):]))
    return frames


# ---------------------------------------------------------------------------
# Cross-protocol SSE tests: provider fixtures → OpenAI egress
# ---------------------------------------------------------------------------


class TestProviderToOpenAiEgress:
    """Verify provider canonical events produce valid OpenAI SSE output."""

    @pytest.mark.asyncio
    async def test_text_stream_to_openai(self, fixtures_dir: Path):
        fixture = (fixtures_dir / "provider_text.sse").read_bytes()
        encoder = OpenAISseEncoder()
        canonical = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        raw = await collect_bytes(encoder.encode(canonical))
        frames = _parse_openai_frames(raw)

        # Must have role chunk, text deltas, finish reason, [DONE]
        assert frames[-1] == "[DONE]"

        role_chunks = [f for f in frames if isinstance(f, dict) and f.get("choices", [{}])[0].get("delta", {}).get("role") == "assistant"]
        assert len(role_chunks) >= 1, "Expected role chunk"

        text_deltas = [
            f for f in frames
            if isinstance(f, dict) and f.get("choices", [{}])[0].get("delta", {}).get("content")
        ]
        combined_text = "".join(
            f["choices"][0]["delta"]["content"] for f in text_deltas
        )
        assert "Hello" in combined_text
        assert "world" in combined_text

        finish_frames = [
            f for f in frames
            if isinstance(f, dict) and f.get("choices", [{}])[0].get("finish_reason") is not None
        ]
        assert len(finish_frames) >= 1
        assert finish_frames[0]["choices"][0]["finish_reason"] == "stop"

        # All dict frames should be chat.completion.chunk
        for f in frames:
            if isinstance(f, dict) and "object" in f:
                assert f["object"] == "chat.completion.chunk"

    @pytest.mark.asyncio
    async def test_tool_use_stream_to_openai(self, fixtures_dir: Path):
        fixture = (fixtures_dir / "provider_tool_use.sse").read_bytes()
        encoder = OpenAISseEncoder()
        canonical = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        raw = await collect_bytes(encoder.encode(canonical))
        frames = _parse_openai_frames(raw)

        assert frames[-1] == "[DONE]"

        # Should have tool_calls in delta
        tool_frames = [
            f for f in frames
            if isinstance(f, dict)
            and "tool_calls" in f.get("choices", [{}])[0].get("delta", {})
        ]
        assert len(tool_frames) >= 1, "Expected tool call frames"

        # First tool frame should have id and function name
        first_tc = tool_frames[0]["choices"][0]["delta"]["tool_calls"][0]
        assert first_tc["id"] == "toolu_1"
        assert first_tc["function"]["name"] == "bash"

        # Finish reason should be tool_calls
        finish_frames = [
            f for f in frames
            if isinstance(f, dict) and f.get("choices", [{}])[0].get("finish_reason") is not None
        ]
        assert finish_frames[0]["choices"][0]["finish_reason"] == "tool_calls"


class TestProviderToAnthropicEgress:
    """Verify the Anthropic egress still works from the same fixtures (regression)."""

    @pytest.mark.asyncio
    async def test_text_stream_to_anthropic(self, fixtures_dir: Path):
        fixture = (fixtures_dir / "provider_text.sse").read_bytes()
        expected = (fixtures_dir / "provider_text.expected").read_bytes()
        encoder = AnthropicSseEncoder()
        canonical = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        actual = await collect_bytes(encoder.encode(canonical))
        assert actual == expected

    @pytest.mark.asyncio
    async def test_tool_use_stream_to_anthropic(self, fixtures_dir: Path):
        fixture = (fixtures_dir / "provider_tool_use.sse").read_bytes()
        expected = (fixtures_dir / "provider_tool_use.expected").read_bytes()
        encoder = AnthropicSseEncoder()
        canonical = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        actual = await collect_bytes(encoder.encode(canonical))
        assert actual == expected


# ---------------------------------------------------------------------------
# Both egress from same canonical events should be structurally consistent
# ---------------------------------------------------------------------------


class TestDualEgressConsistency:
    """Ensure Anthropic and OpenAI egress produce semantically consistent output from same events."""

    @pytest.mark.asyncio
    async def test_text_content_consistent(self, fixtures_dir: Path):
        fixture = (fixtures_dir / "provider_text.sse").read_bytes()

        # Anthropic egress
        anthropic_encoder = AnthropicSseEncoder()
        canonical_a = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        anthropic_raw = await collect_bytes(anthropic_encoder.encode(canonical_a))
        anthropic_frames = _parse_anthropic_frames(anthropic_raw)

        # OpenAI egress
        openai_encoder = OpenAISseEncoder()
        canonical_o = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        openai_raw = await collect_bytes(openai_encoder.encode(canonical_o))
        openai_frames = _parse_openai_frames(openai_raw)

        # Extract text from Anthropic
        anthropic_text_deltas = [
            f["delta"]["text"]
            for f in anthropic_frames
            if f.get("type") == "content_block_delta"
            and f.get("delta", {}).get("type") == "text_delta"
        ]
        anthropic_text = "".join(anthropic_text_deltas)

        # Extract text from OpenAI
        openai_text_deltas = [
            f["choices"][0]["delta"]["content"]
            for f in openai_frames
            if isinstance(f, dict) and f.get("choices", [{}])[0].get("delta", {}).get("content")
        ]
        openai_text = "".join(openai_text_deltas)

        assert anthropic_text == openai_text, (
            f"Text mismatch: Anthropic={anthropic_text!r} vs OpenAI={openai_text!r}"
        )

    @pytest.mark.asyncio
    async def test_stop_reason_consistent(self, fixtures_dir: Path):
        fixture = (fixtures_dir / "provider_text.sse").read_bytes()

        # Anthropic egress
        anthropic_encoder = AnthropicSseEncoder()
        canonical_a = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        anthropic_raw = await collect_bytes(anthropic_encoder.encode(canonical_a))
        anthropic_frames = _parse_anthropic_frames(anthropic_raw)

        anthropic_stop = None
        for f in anthropic_frames:
            if f.get("type") == "message_delta":
                anthropic_stop = f.get("delta", {}).get("stop_reason")

        # OpenAI egress
        openai_encoder = OpenAISseEncoder()
        canonical_o = await _canonical_stream(fixture, "anthropic/claude-sonnet-4")
        openai_raw = await collect_bytes(openai_encoder.encode(canonical_o))
        openai_frames = _parse_openai_frames(openai_raw)

        openai_finish = None
        for f in openai_frames:
            if isinstance(f, dict) and f.get("choices", [{}])[0].get("finish_reason") is not None:
                openai_finish = f["choices"][0]["finish_reason"]

        # Anthropic "end_turn" should map to OpenAI "stop"
        assert anthropic_stop == "end_turn"
        assert openai_finish == "stop"
