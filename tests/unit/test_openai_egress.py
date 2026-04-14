"""Tests for the OpenAI Chat Completions egress encoders."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from llm_proxy.application.openai_egress import (
    OpenAIResponseEncoder,
    OpenAISseEncoder,
    _finish_reason,
    _openai_usage,
)
from llm_proxy.domain.enums import Role
from llm_proxy.domain.models import (
    ChatResponse,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    ErrorEvent,
    InputJsonDelta,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    PingEvent,
    TextBlock,
    TextDelta,
    ToolUseBlock,
    Usage,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _collect_frames(encoder: OpenAISseEncoder, events: list) -> list[bytes]:
    async def _gen():
        for e in events:
            yield e

    frames = []
    async for frame in encoder.encode(_gen()):
        frames.append(frame)
    return frames


def _parse_sse_data(frame: bytes) -> dict | str:
    text = frame.decode("utf-8").strip()
    if text.startswith("data: "):
        payload = text[len("data: "):]
        if payload == "[DONE]":
            return "[DONE]"
        return json.loads(payload)
    return text


def _base_response(**overrides) -> ChatResponse:
    defaults = {
        "id": "resp_123",
        "role": Role.ASSISTANT,
        "model": "gpt-4.1",
        "content": (TextBlock(text="Hello"),),
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": Usage(input_tokens=10, output_tokens=5),
    }
    defaults.update(overrides)
    return ChatResponse(**defaults)


def _base_message_start(**overrides) -> MessageStartEvent:
    return MessageStartEvent(message=_base_response(**overrides))


# ---------------------------------------------------------------------------
# finish_reason mapping
# ---------------------------------------------------------------------------


class TestFinishReasonMapping:
    def test_end_turn(self):
        assert _finish_reason("end_turn") == "stop"

    def test_max_tokens(self):
        assert _finish_reason("max_tokens") == "length"

    def test_tool_use(self):
        assert _finish_reason("tool_use") == "tool_calls"

    def test_stop_sequence(self):
        assert _finish_reason("stop_sequence") == "stop"

    def test_none(self):
        assert _finish_reason(None) is None

    def test_unknown_defaults_to_stop(self):
        assert _finish_reason("unknown_reason") == "stop"


# ---------------------------------------------------------------------------
# Usage mapping
# ---------------------------------------------------------------------------


class TestOpenAIUsage:
    def test_basic(self):
        u = _openai_usage(Usage(input_tokens=10, output_tokens=5))
        assert u == {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}

    def test_none_tokens(self):
        u = _openai_usage(Usage())
        assert u == {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    def test_reasoning_tokens(self):
        u = _openai_usage(Usage(input_tokens=10, output_tokens=5, reasoning_tokens=3))
        assert u["prompt_tokens"] == 10
        assert u["completion_tokens"] == 5
        assert u["completion_tokens_details"] == {"reasoning_tokens": 3}


# ---------------------------------------------------------------------------
# SSE Encoder
# ---------------------------------------------------------------------------


class TestOpenAISseEncoder:
    @pytest.mark.asyncio
    async def test_text_stream(self):
        events = [
            _base_message_start(),
            ContentBlockStartEvent(index=0, block=TextBlock(text="")),
            ContentBlockDeltaEvent(index=0, delta=TextDelta(text="Hi")),
            ContentBlockDeltaEvent(index=0, delta=TextDelta(text=" there")),
            ContentBlockStopEvent(index=0),
            MessageDeltaEvent(stop_reason="end_turn", usage=Usage(input_tokens=10, output_tokens=5)),
            MessageStopEvent(),
        ]
        encoder = OpenAISseEncoder()
        frames = await _collect_frames(encoder, events)

        # Parse all frames
        parsed = [_parse_sse_data(f) for f in frames]

        # First: role chunk
        assert parsed[0]["choices"][0]["delta"]["role"] == "assistant"
        assert parsed[0]["object"] == "chat.completion.chunk"

        # Text deltas
        assert parsed[1]["choices"][0]["delta"]["content"] == "Hi"
        assert parsed[2]["choices"][0]["delta"]["content"] == " there"

        # Finish reason
        assert parsed[3]["choices"][0]["finish_reason"] == "stop"

        # [DONE]
        assert parsed[-1] == "[DONE]"

    @pytest.mark.asyncio
    async def test_tool_call_stream(self):
        events = [
            _base_message_start(),
            ContentBlockStartEvent(
                index=0,
                block=ToolUseBlock(id="call_123", name="get_weather", input={}),
            ),
            ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='{"ci')),
            ContentBlockDeltaEvent(index=0, delta=InputJsonDelta(partial_json='ty":"Rome"}')),
            ContentBlockStopEvent(index=0),
            MessageDeltaEvent(stop_reason="tool_use"),
            MessageStopEvent(),
        ]
        encoder = OpenAISseEncoder()
        frames = await _collect_frames(encoder, events)
        parsed = [_parse_sse_data(f) for f in frames]

        # Role chunk
        assert parsed[0]["choices"][0]["delta"]["role"] == "assistant"

        # Tool call start
        tc = parsed[1]["choices"][0]["delta"]["tool_calls"][0]
        assert tc["id"] == "call_123"
        assert tc["function"]["name"] == "get_weather"

        # Tool call arguments deltas
        tc_arg1 = parsed[2]["choices"][0]["delta"]["tool_calls"][0]
        assert tc_arg1["function"]["arguments"] == '{"ci'

        # Finish
        finish_frame = parsed[4]
        assert finish_frame["choices"][0]["finish_reason"] == "tool_calls"

    @pytest.mark.asyncio
    async def test_ping_and_error(self):
        events = [
            _base_message_start(),
            PingEvent(),
            ErrorEvent(message="something broke", error_type="server_error"),
            MessageStopEvent(),
        ]
        encoder = OpenAISseEncoder()
        frames = await _collect_frames(encoder, events)
        parsed = [_parse_sse_data(f) for f in frames]

        # Ping is skipped (no frame)
        # Error frame
        error_frame = parsed[1]
        assert error_frame["error"]["message"] == "something broke"

    @pytest.mark.asyncio
    async def test_done_always_last(self):
        events = [
            _base_message_start(),
            MessageStopEvent(),
        ]
        encoder = OpenAISseEncoder()
        frames = await _collect_frames(encoder, events)
        assert _parse_sse_data(frames[-1]) == "[DONE]"


# ---------------------------------------------------------------------------
# Response Encoder
# ---------------------------------------------------------------------------


class TestOpenAIResponseEncoder:
    def test_text_response(self):
        resp = _base_response()
        encoder = OpenAIResponseEncoder()
        result = encoder.encode(resp)

        assert result["id"] == "resp_123"
        assert result["object"] == "chat.completion"
        assert result["model"] == "gpt-4.1"
        choice = result["choices"][0]
        assert choice["message"]["role"] == "assistant"
        assert choice["message"]["content"] == "Hello"
        assert choice["finish_reason"] == "stop"
        assert result["usage"]["prompt_tokens"] == 10
        assert result["usage"]["completion_tokens"] == 5
        assert result["usage"]["total_tokens"] == 15

    def test_tool_call_response(self):
        resp = _base_response(
            content=(
                ToolUseBlock(id="call_abc", name="search", input={"q": "test"}),
            ),
            stop_reason="tool_use",
        )
        encoder = OpenAIResponseEncoder()
        result = encoder.encode(resp)

        choice = result["choices"][0]
        assert choice["finish_reason"] == "tool_calls"
        assert choice["message"]["content"] is None
        tc = choice["message"]["tool_calls"]
        assert len(tc) == 1
        assert tc[0]["id"] == "call_abc"
        assert tc[0]["function"]["name"] == "search"
        assert json.loads(tc[0]["function"]["arguments"]) == {"q": "test"}

    def test_mixed_text_and_tools(self):
        resp = _base_response(
            content=(
                TextBlock(text="Let me check."),
                ToolUseBlock(id="call_1", name="look_up", input={}),
            ),
            stop_reason="tool_use",
        )
        encoder = OpenAIResponseEncoder()
        result = encoder.encode(resp)

        choice = result["choices"][0]
        assert choice["message"]["content"] == "Let me check."
        assert len(choice["message"]["tool_calls"]) == 1
