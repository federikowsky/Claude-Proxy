from __future__ import annotations

import codecs
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any

import httpx

from claude_proxy.domain.errors import (
    ProviderAuthError,
    ProviderProtocolError,
    UpstreamTimeoutError,
)
from claude_proxy.domain.models import (
    ChatRequest,
    ModelInfo,
    ProviderEvent,
    RawError,
    RawReasoningDelta,
    RawStop,
    RawTextDelta,
    RawUnknown,
    RawUsage,
    Usage,
)
from claude_proxy.infrastructure.config import ProviderSettings
from claude_proxy.infrastructure.http import SharedAsyncClientManager
from claude_proxy.jsonutil import json_loads

REASONING_BLOCK_TYPES = {"thinking", "redacted_thinking", "reasoning"}
REASONING_DELTA_TYPES = {"thinking_delta", "signature_delta", "reasoning_delta"}


@dataclass(slots=True, frozen=True)
class SseMessage:
    event: str | None
    data: str


class IncrementalSseParser:
    async def parse(self, chunks: AsyncIterator[bytes]) -> AsyncIterator[SseMessage]:
        decoder = codecs.getincrementaldecoder("utf-8")()
        pending = ""
        event_name: str | None = None
        data_lines: list[str] = []

        async for chunk in chunks:
            pending += decoder.decode(chunk)
            while True:
                newline_index = pending.find("\n")
                if newline_index < 0:
                    break
                line = pending[:newline_index]
                pending = pending[newline_index + 1 :]
                if line.endswith("\r"):
                    line = line[:-1]

                if not line:
                    if data_lines:
                        yield SseMessage(event=event_name, data="\n".join(data_lines))
                    event_name = None
                    data_lines = []
                    continue

                if line.startswith(":"):
                    continue
                if line.startswith("event:"):
                    event_name = line[6:]
                    if event_name.startswith(" "):
                        event_name = event_name[1:]
                    continue
                if line.startswith("data:"):
                    data = line[5:]
                    if data.startswith(" "):
                        data = data[1:]
                    data_lines.append(data)

        pending += decoder.decode(b"", final=True)
        if pending or data_lines or event_name:
            raise ProviderProtocolError("truncated SSE stream")


class OpenRouterTranslator:
    def to_payload(self, request: ChatRequest, model: ModelInfo) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": model.name,
            "messages": [
                {
                    "role": message.role.value,
                    "content": message.text,
                }
                for message in request.messages
            ],
            "max_tokens": request.max_tokens,
            "stream": True,
        }
        if request.system:
            payload["system"] = request.system
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.metadata:
            payload["metadata"] = dict(request.metadata)
        return payload


class OpenRouterEventMapper:
    def __init__(self) -> None:
        self._block_types: dict[int, str] = {}
        self._stop_reason: str | None = None

    def map_message(self, message: SseMessage) -> ProviderEvent | None:
        if message.data == "[DONE]":
            return RawStop(stop_reason=self._stop_reason)

        try:
            payload = json_loads(message.data)
        except Exception as exc:
            raise ProviderProtocolError("invalid upstream JSON event") from exc

        if not isinstance(payload, dict):
            raise ProviderProtocolError("invalid upstream event payload")

        event_type = (message.event or payload.get("type") or "").strip()
        if not event_type:
            return RawUnknown(event_type="unknown")

        if event_type == "message_start":
            message_payload = payload.get("message", {})
            usage_payload = message_payload.get("usage", {}) if isinstance(message_payload, dict) else {}
            if isinstance(usage_payload, dict) and usage_payload:
                return RawUsage(usage=self._usage_from_payload(usage_payload))
            return None

        if event_type == "content_block_start":
            index = int(payload.get("index", 0))
            block = payload.get("content_block", {})
            if isinstance(block, dict):
                self._block_types[index] = str(block.get("type", "unknown"))
            return None

        if event_type == "content_block_delta":
            return self._map_delta(payload)

        if event_type == "content_block_stop":
            self._block_types.pop(int(payload.get("index", 0)), None)
            return None

        if event_type == "message_delta":
            delta = payload.get("delta", {})
            if isinstance(delta, dict):
                self._stop_reason = delta.get("stop_reason") or self._stop_reason
            usage_payload = payload.get("usage")
            if isinstance(usage_payload, dict) and usage_payload:
                return RawUsage(usage=self._usage_from_payload(usage_payload))
            return None

        if event_type == "message_stop":
            return RawStop(stop_reason=self._stop_reason)

        if event_type == "error":
            error = payload.get("error", {})
            if isinstance(error, dict):
                return RawError(
                    message=str(error.get("message") or "provider error"),
                    error_type=str(error.get("type") or "provider_error"),
                )
            return RawError(message="provider error")

        return RawUnknown(event_type=event_type)

    def _map_delta(self, payload: dict[str, object]) -> ProviderEvent | None:
        index = int(payload.get("index", 0))
        delta = payload.get("delta", {})
        if not isinstance(delta, dict):
            return RawUnknown(event_type="content_block_delta")

        block_type = self._block_types.get(index, "unknown")
        delta_type = str(delta.get("type", ""))
        text = str(delta.get("text", ""))

        if delta_type == "signature_delta":
            return None
        if block_type in REASONING_BLOCK_TYPES or delta_type in REASONING_DELTA_TYPES:
            if text:
                return RawReasoningDelta(text=text)
            return None
        if delta_type == "text_delta":
            if text:
                return RawTextDelta(text=text)
            return None
        return RawUnknown(event_type=delta_type or "content_block_delta")

    @staticmethod
    def _usage_from_payload(payload: dict[str, object]) -> Usage:
        input_tokens = payload.get("input_tokens")
        output_tokens = payload.get("output_tokens")
        return Usage(
            input_tokens=int(input_tokens) if isinstance(input_tokens, int) else None,
            output_tokens=int(output_tokens) if isinstance(output_tokens, int) else None,
        )


class OpenRouterProvider:
    def __init__(
        self,
        *,
        settings: ProviderSettings,
        client_manager: SharedAsyncClientManager,
        translator: OpenRouterTranslator | None = None,
        parser: IncrementalSseParser | None = None,
    ) -> None:
        self._settings = settings
        self._client_manager = client_manager
        self._translator = translator or OpenRouterTranslator()
        self._parser = parser or IncrementalSseParser()

    async def stream(
        self,
        request: ChatRequest,
        model: ModelInfo,
    ) -> AsyncIterator[ProviderEvent]:
        client = await self._client_manager.get_client()
        payload = self._translator.to_payload(request, model)
        stream_context = client.stream(
            "POST",
            self._messages_url(),
            headers=self._headers(),
            json=payload,
            timeout=self._timeout(),
        )
        response = await self._open_stream(stream_context)
        mapper = OpenRouterEventMapper()

        async def iterator() -> AsyncIterator[ProviderEvent]:
            try:
                async for message in self._parser.parse(response.aiter_bytes()):
                    mapped = mapper.map_message(message)
                    if mapped is not None:
                        yield mapped
            finally:
                await stream_context.__aexit__(None, None, None)

        return iterator()

    async def _open_stream(
        self,
        stream_context: Any,
    ) -> httpx.Response:
        try:
            response = await stream_context.__aenter__()
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError("OpenRouter timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"OpenRouter request failed: {exc}") from exc

        if response.status_code >= 400:
            body = await response.aread()
            await stream_context.__aexit__(None, None, None)
            message = _provider_error_message(body)
            if response.status_code == 401:
                raise ProviderAuthError(message or "OpenRouter authentication failed")
            raise ProviderProtocolError(message or f"OpenRouter returned HTTP {response.status_code}")
        return response

    def _messages_url(self) -> str:
        base_url = self._settings.base_url.rstrip("/")
        return f"{base_url}/messages"

    def _headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
            "Accept": "text/event-stream",
            "Content-Type": "application/json",
            "X-OpenRouter-Title": self._settings.app_name,
        }
        if self._settings.app_url:
            headers["HTTP-Referer"] = self._settings.app_url
        if self._settings.debug_echo_upstream_body:
            headers["X-Debug"] = "1"
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._settings.connect_timeout_seconds,
            read=self._settings.read_timeout_seconds,
            write=self._settings.write_timeout_seconds,
            pool=self._settings.pool_timeout_seconds,
        )


def _provider_error_message(body: bytes) -> str | None:
    if not body:
        return None
    try:
        payload = json_loads(body)
    except Exception:
        text = body.decode("utf-8", errors="ignore").strip()
        return text or None
    if isinstance(payload, dict):
        error = payload.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str) and message:
                return message
        message = payload.get("message")
        if isinstance(message, str) and message:
            return message
    return None
