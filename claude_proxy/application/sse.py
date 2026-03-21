from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from uuid import uuid4

from claude_proxy.domain.models import (
    DomainEvent,
    ErrorEvent,
    MessageStartEvent,
    MessageStopEvent,
    ProviderWarningEvent,
    TextDeltaEvent,
    TextStartEvent,
    TextStopEvent,
    Usage,
    UsageEvent,
)
from claude_proxy.jsonutil import json_dumps


def _sse_frame(event: str, payload: dict[str, object]) -> bytes:
    return b"event: " + event.encode("utf-8") + b"\n" + b"data: " + json_dumps(payload) + b"\n\n"


class AnthropicSseEncoder:
    def __init__(self, message_id_factory: Callable[[], str] | None = None) -> None:
        self._message_id_factory = message_id_factory or (lambda: f"msg_{uuid4().hex}")

    async def encode(self, events: AsyncIterator[DomainEvent]) -> AsyncIterator[bytes]:
        message_id = self._message_id_factory()
        model = "unknown"
        usage = Usage()

        async for event in events:
            if isinstance(event, MessageStartEvent):
                model = event.model
                yield _sse_frame(
                    "message_start",
                    {
                        "type": "message_start",
                        "message": {
                            "id": message_id,
                            "type": "message",
                            "role": "assistant",
                            "model": model,
                            "content": [],
                            "stop_reason": None,
                            "stop_sequence": None,
                            "usage": {"input_tokens": 0, "output_tokens": 0},
                        },
                    },
                )
                continue

            if isinstance(event, TextStartEvent):
                yield _sse_frame(
                    "content_block_start",
                    {
                        "type": "content_block_start",
                        "index": event.index,
                        "content_block": {"type": "text", "text": ""},
                    },
                )
                continue

            if isinstance(event, TextDeltaEvent):
                if event.text:
                    yield _sse_frame(
                        "content_block_delta",
                        {
                            "type": "content_block_delta",
                            "index": 0,
                            "delta": {"type": "text_delta", "text": event.text},
                        },
                    )
                continue

            if isinstance(event, TextStopEvent):
                yield _sse_frame(
                    "content_block_stop",
                    {
                        "type": "content_block_stop",
                        "index": event.index,
                    },
                )
                continue

            if isinstance(event, UsageEvent):
                usage = event.usage
                continue

            if isinstance(event, ErrorEvent):
                yield _sse_frame(
                    "error",
                    {
                        "type": "error",
                        "error": {
                            "type": event.error_type,
                            "message": event.message,
                        },
                    },
                )
                continue

            if isinstance(event, ProviderWarningEvent):
                continue

            if isinstance(event, MessageStopEvent):
                payload: dict[str, object] = {
                    "type": "message_delta",
                    "delta": {},
                }
                usage_payload = usage.to_payload()
                if usage_payload:
                    payload["usage"] = usage_payload
                if event.stop_reason is not None:
                    payload["delta"] = {"stop_reason": event.stop_reason}
                yield _sse_frame("message_delta", payload)
                yield _sse_frame("message_stop", {"type": "message_stop"})

