"""OpenAI Chat Completions egress encoders.

Converts the canonical event stream and response into OpenAI-format output,
implementing the SseEncoder and ResponseEncoder protocols.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from uuid import uuid4

from llm_proxy.domain.models import (
    CanonicalEvent,
    ChatResponse,
    ContentBlock,
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
    ThinkingBlock,
    ToolUseBlock,
    Usage,
)
from llm_proxy.jsonutil import json_dumps

# ---------------------------------------------------------------------------
# Canonical stop_reason → OpenAI finish_reason (reverse of _FINISH_REASON_MAP)
# ---------------------------------------------------------------------------
_STOP_REASON_TO_FINISH: dict[str, str] = {
    "end_turn": "stop",
    "max_tokens": "length",
    "tool_use": "tool_calls",
    "stop_sequence": "stop",
}


def _finish_reason(stop_reason: str | None) -> str | None:
    if stop_reason is None:
        return None
    return _STOP_REASON_TO_FINISH.get(stop_reason, "stop")


def _openai_usage(usage: Usage) -> dict[str, int]:
    inp = usage.input_tokens or 0
    out = usage.output_tokens or 0
    result: dict[str, int] = {
        "prompt_tokens": inp,
        "completion_tokens": out,
        "total_tokens": inp + out,
    }
    if usage.reasoning_tokens is not None:
        result["completion_tokens_details"] = {"reasoning_tokens": usage.reasoning_tokens}  # type: ignore[assignment]
    return result


def _sse_frame(payload: bytes) -> bytes:
    return b"data: " + payload + b"\n\n"


def _content_block_to_openai(block: ContentBlock) -> dict[str, object]:
    """Convert a canonical ContentBlock to an OpenAI choice message content item."""
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "function",
            "id": block.id,
            "function": {"name": block.name, "arguments": _serialize_input(block.input)},
        }
    if isinstance(block, ThinkingBlock):
        return {"type": "text", "text": block.thinking}
    return {"type": "text", "text": ""}


def _serialize_input(value: object) -> str:
    """Serialize tool input to JSON string for OpenAI function arguments."""
    if isinstance(value, str):
        return value
    return json_dumps(value).decode("utf-8")


# ---------------------------------------------------------------------------
# Streaming encoder
# ---------------------------------------------------------------------------


class OpenAISseEncoder:
    """Converts canonical events → OpenAI streaming SSE (data: {json}\n\n + data: [DONE])."""

    def __init__(self) -> None:
        self._chat_id: str = ""
        self._model: str = ""
        self._created: int = 0
        # Track accumulated tool call arguments per index so we can emit
        # incremental function.arguments deltas.
        self._tool_indices: dict[int, str] = {}

    async def encode(self, events: AsyncIterator[CanonicalEvent]) -> AsyncIterator[bytes]:
        async for event in events:
            chunk = self._encode_event(event)
            if chunk is not None:
                yield _sse_frame(chunk)

        # Terminal frame
        yield b"data: [DONE]\n\n"

    def _encode_event(self, event: CanonicalEvent) -> bytes | None:
        if isinstance(event, MessageStartEvent):
            self._chat_id = event.message.id or f"chatcmpl-{uuid4().hex[:24]}"
            self._model = event.message.model
            self._created = int(time.time())
            # Emit the role chunk
            return self._chunk(
                delta={"role": "assistant", "content": ""},
                finish_reason=None,
            )

        if isinstance(event, ContentBlockStartEvent):
            if isinstance(event.block, ToolUseBlock):
                self._tool_indices[event.index] = ""
                idx = len(self._tool_indices) - 1
                return self._chunk(
                    delta={
                        "tool_calls": [
                            {
                                "index": idx,
                                "id": event.block.id,
                                "type": "function",
                                "function": {
                                    "name": event.block.name,
                                    "arguments": "",
                                },
                            }
                        ]
                    },
                    finish_reason=None,
                )
            # Text block start — no content yet
            return None

        if isinstance(event, ContentBlockDeltaEvent):
            if isinstance(event.delta, TextDelta):
                return self._chunk(
                    delta={"content": event.delta.text},
                    finish_reason=None,
                )
            if isinstance(event.delta, InputJsonDelta):
                # Find tool call index for this content block
                if event.index in self._tool_indices:
                    idx = list(self._tool_indices.keys()).index(event.index)
                    return self._chunk(
                        delta={
                            "tool_calls": [
                                {
                                    "index": idx,
                                    "function": {
                                        "arguments": event.delta.partial_json,
                                    },
                                }
                            ]
                        },
                        finish_reason=None,
                    )
            return None

        if isinstance(event, ContentBlockStopEvent):
            return None

        if isinstance(event, MessageDeltaEvent):
            if event.stop_reason is not None:
                finish = _finish_reason(event.stop_reason)
                chunk_data: dict[str, object] = {
                    "id": self._chat_id,
                    "object": "chat.completion.chunk",
                    "created": self._created,
                    "model": self._model,
                    "choices": [
                        {
                            "index": 0,
                            "delta": {},
                            "finish_reason": finish,
                        }
                    ],
                }
                if event.usage is not None:
                    chunk_data["usage"] = _openai_usage(event.usage)
                return json_dumps(chunk_data)
            return None

        if isinstance(event, MessageStopEvent):
            return None

        if isinstance(event, PingEvent):
            return None

        if isinstance(event, ErrorEvent):
            return json_dumps(
                {
                    "error": {
                        "message": event.message,
                        "type": event.error_type,
                    }
                }
            )

        return None

    def _chunk(
        self,
        *,
        delta: dict[str, object],
        finish_reason: str | None,
    ) -> bytes:
        return json_dumps(
            {
                "id": self._chat_id,
                "object": "chat.completion.chunk",
                "created": self._created,
                "model": self._model,
                "choices": [
                    {
                        "index": 0,
                        "delta": delta,
                        "finish_reason": finish_reason,
                    }
                ],
            }
        )

    @staticmethod
    def format_bridge_error_sse(err: object) -> bytes:
        """Emit a single SSE frame for a bridge-level error."""
        msg = str(err)
        return _sse_frame(
            json_dumps({"error": {"message": msg, "type": "proxy_error"}})
        )


# ---------------------------------------------------------------------------
# Non-streaming encoder
# ---------------------------------------------------------------------------


class OpenAIResponseEncoder:
    """Converts ChatResponse → OpenAI Chat Completions JSON response."""

    def encode(self, response: ChatResponse) -> dict[str, object]:
        message = self._build_message(response)
        result: dict[str, object] = {
            "id": response.id or f"chatcmpl-{uuid4().hex[:24]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": response.model,
            "choices": [
                {
                    "index": 0,
                    "message": message,
                    "finish_reason": _finish_reason(response.stop_reason) or "stop",
                }
            ],
            "usage": _openai_usage(response.usage),
        }
        return result

    @staticmethod
    def _build_message(response: ChatResponse) -> dict[str, object]:
        text_parts: list[str] = []
        tool_calls: list[dict[str, object]] = []

        for block in response.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": _serialize_input(block.input),
                        },
                    }
                )
            elif isinstance(block, ThinkingBlock):
                text_parts.append(block.thinking)

        msg: dict[str, object] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        }
        if tool_calls:
            msg["tool_calls"] = tool_calls

        return msg
