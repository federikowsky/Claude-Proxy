from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from uuid import uuid4

from claude_proxy.domain.errors import BridgeError
from claude_proxy.domain.models import (
    CanonicalEvent,
    ChatResponse,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    ErrorEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    PingEvent,
)
from claude_proxy.domain.serialization import content_block_to_payload, delta_to_payload, response_to_payload
from claude_proxy.jsonutil import json_dumps


def _sse_frame(event: str, payload: dict[str, object]) -> bytes:
    return b"event: " + event.encode("utf-8") + b"\n" + b"data: " + json_dumps(payload) + b"\n\n"


class AnthropicSseEncoder:
    def __init__(self, message_id_factory: Callable[[], str] | None = None) -> None:
        self._message_id_factory = message_id_factory or (lambda: f"msg_{uuid4().hex}")

    @staticmethod
    def format_bridge_error_sse(err: BridgeError) -> bytes:
        """Single SSE frame matching the JSON error envelope used for non-stream responses."""
        return _sse_frame("error", err.to_payload())

    async def encode(self, events: AsyncIterator[CanonicalEvent]) -> AsyncIterator[bytes]:
        async for event in events:
            if isinstance(event, MessageStartEvent):
                message = self._start_message(event.message)
                yield _sse_frame(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": message.id,
                            "type": "message",
                            "role": message.role.value,
                            "model": message.model,
                            "content": [],
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": message.usage.to_payload() or {"input_tokens": 0, "output_tokens": 0},
                        },
                    },
                )
                continue

            if isinstance(event, ContentBlockStartEvent):
                yield _sse_frame(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": event.index,
                        "content_block": content_block_to_payload(event.block),
                    },
                )
                continue

            if isinstance(event, ContentBlockDeltaEvent):
                yield _sse_frame(
                    "content_block_delta",
                    {
                        "type": "content_block_delta",
                        "index": event.index,
                        "delta": delta_to_payload(event.delta),
                    },
                )
                continue

            if isinstance(event, ContentBlockStopEvent):
                yield _sse_frame(
                    "content_block_stop",
                    {"type": "content_block_stop", "index": event.index},
                )
                continue

            if isinstance(event, MessageDeltaEvent):
                payload: dict[str, object] = {"type": "message_delta", "delta": {}}
                if event.stop_reason is not None:
                    payload["delta"] = {
                        **payload["delta"],
                        "stop_reason": event.stop_reason,
                    }
                if event.stop_sequence is not None:
                    payload["delta"] = {
                        **payload["delta"],
                        "stop_sequence": event.stop_sequence,
                    }
                if event.usage is not None and event.usage.to_payload():
                    payload["usage"] = event.usage.to_payload()
                payload.update(dict(event.extras))
                yield _sse_frame("message_delta", payload)
                continue

            if isinstance(event, MessageStopEvent):
                yield _sse_frame("message_stop", {"type": "message_stop"})
                continue

            if isinstance(event, PingEvent):
                yield _sse_frame("ping", {"type": "ping", **dict(event.payload)})
                continue

            if isinstance(event, ErrorEvent):
                yield _sse_frame(
                    "error",
                    {
                        "type": "error",
                        "error": {"type": event.error_type, "message": event.message},
                    },
                )

    def _start_message(self, message: ChatResponse) -> ChatResponse:
        if message.id:
            return message
        return ChatResponse(
            id=self._message_id_factory(),
            role=message.role,
            model=message.model,
            content=message.content,
            stop_reason=message.stop_reason,
            stop_sequence=message.stop_sequence,
            usage=message.usage,
            metadata=message.metadata,
            extras=message.extras,
        )


class AnthropicResponseEncoder:
    def encode(self, response: ChatResponse) -> dict[str, object]:
        return response_to_payload(response)
