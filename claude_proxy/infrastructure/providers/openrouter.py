from __future__ import annotations

import codecs
from collections.abc import AsyncIterator, Mapping
from dataclasses import dataclass
from typing import Any

import httpx

from claude_proxy.domain.errors import ProviderAuthError, ProviderProtocolError, UpstreamTimeoutError
from claude_proxy.domain.models import (
    CanonicalEvent,
    ChatRequest,
    ChatResponse,
    ContentBlock,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    ErrorEvent,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    PingEvent,
    ProviderWarningEvent,
)
from claude_proxy.domain.serialization import (
    content_block_from_payload,
    content_block_to_payload,
    delta_from_payload,
    response_from_payload,
    thinking_config_to_payload,
    tool_choice_to_payload,
    tool_definition_to_payload,
    usage_from_payload,
)
from claude_proxy.infrastructure.config import ProviderSettings
from claude_proxy.infrastructure.http import SharedAsyncClientManager
from claude_proxy.jsonutil import json_loads


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
    def __init__(self, passthrough_request_fields: tuple[str, ...] = ()) -> None:
        self._passthrough_request_fields = set(passthrough_request_fields)

    def to_payload(self, request: ChatRequest, model: ModelInfo) -> dict[str, object]:
        payload: dict[str, object] = {
            "model": model.name,
            "messages": [
                {
                    "role": message.role.value,
                    "content": [content_block_to_payload(block) for block in message.content],
                }
                for message in request.messages
            ],
            "max_tokens": request.max_tokens,
            "stream": request.stream,
        }
        if request.system:
            payload["system"] = [content_block_to_payload(block) for block in request.system]
        if request.metadata is not None:
            payload["metadata"] = dict(request.metadata)
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop_sequences:
            payload["stop_sequences"] = list(request.stop_sequences)
        if request.tools:
            payload["tools"] = [tool_definition_to_payload(tool) for tool in request.tools]
        if request.tool_choice is not None:
            payload["tool_choice"] = tool_choice_to_payload(request.tool_choice)
        if request.thinking is not None:
            payload["thinking"] = thinking_config_to_payload(request.thinking)
        for key, value in request.extensions.items():
            if key in self._passthrough_request_fields:
                payload[key] = value
        return payload


class OpenRouterStreamNormalizer:
    def __init__(self) -> None:
        self._blocks: dict[int, ContentBlock] = {}

    def normalize(self, message: SseMessage) -> CanonicalEvent | None:
        if message.data == "[DONE]":
            return MessageStopEvent()

        try:
            payload = json_loads(message.data)
        except Exception as exc:
            raise ProviderProtocolError("invalid upstream JSON event") from exc
        if not isinstance(payload, dict):
            raise ProviderProtocolError("invalid upstream event payload")

        event_type = (message.event or payload.get("type") or "").strip()
        if not event_type:
            return ProviderWarningEvent(message="unknown_provider_event", payload={"payload": payload})

        if event_type == "message_start":
            return self._message_start(payload)
        if event_type == "content_block_start":
            return self._content_block_start(payload)
        if event_type == "content_block_delta":
            return self._content_block_delta(payload)
        if event_type == "content_block_stop":
            return self._content_block_stop(payload)
        if event_type == "message_delta":
            return MessageDeltaEvent(
                stop_reason=_string_or_none(_mapping(payload.get("delta")).get("stop_reason")),
                stop_sequence=_string_or_none(_mapping(payload.get("delta")).get("stop_sequence")),
                usage=usage_from_payload(payload.get("usage")) if isinstance(payload.get("usage"), Mapping) else None,
                extras=_extras(payload, {"type", "delta", "usage"}),
            )
        if event_type == "message_stop":
            return MessageStopEvent()
        if event_type == "ping":
            return PingEvent(payload=_extras(payload, {"type"}))
        if event_type == "error":
            error = _mapping(payload.get("error"))
            return ErrorEvent(
                message=_string_or_none(error.get("message")) or "provider error",
                error_type=_string_or_none(error.get("type")) or "provider_error",
            )
        return ProviderWarningEvent(message="unknown_provider_event", payload={"event_type": event_type})

    def _message_start(self, payload: dict[str, Any]) -> MessageStartEvent:
        message_payload = _mapping(payload.get("message"))
        response = ChatResponse(
            id=_string_or_none(message_payload.get("id")) or "",
            role=_role_or_default(message_payload.get("role")),
            model=_string_or_none(message_payload.get("model")) or "",
            content=(),
            stop_reason=None,
            stop_sequence=None,
            usage=usage_from_payload(message_payload.get("usage")),
            metadata=dict(message_payload.get("metadata")) if isinstance(message_payload.get("metadata"), Mapping) else None,
            extras=_extras(
                message_payload,
                {"id", "type", "role", "model", "content", "stop_reason", "stop_sequence", "usage", "metadata"},
            ),
        )
        return MessageStartEvent(message=response)

    def _content_block_start(self, payload: dict[str, Any]) -> ContentBlockStartEvent:
        index = _int_or_default(payload.get("index"), 0)
        block = content_block_from_payload(_mapping(payload.get("content_block")), strict=False)
        self._blocks[index] = block
        return ContentBlockStartEvent(index=index, block=block)

    def _content_block_delta(self, payload: dict[str, Any]) -> CanonicalEvent | None:
        index = _int_or_default(payload.get("index"), 0)
        block = self._blocks.get(index)
        delta_payload = _mapping(payload.get("delta"))
        delta = delta_from_payload(delta_payload, block=block)
        if delta is None:
            return None
        return ContentBlockDeltaEvent(index=index, delta=delta)

    def _content_block_stop(self, payload: dict[str, Any]) -> ContentBlockStopEvent:
        index = _int_or_default(payload.get("index"), 0)
        self._blocks.pop(index, None)
        return ContentBlockStopEvent(index=index)


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

    async def stream(self, request: ChatRequest, model: ModelInfo) -> AsyncIterator[CanonicalEvent]:
        client = await self._client_manager.get_client()
        payload = self._translator.to_payload(request, model)
        stream_context = client.stream(
            "POST",
            self._messages_url(),
            headers=self._headers(accept="text/event-stream"),
            json=payload,
            timeout=self._timeout(),
        )
        response = await self._open_stream(stream_context)
        normalizer = OpenRouterStreamNormalizer()

        async def iterator() -> AsyncIterator[CanonicalEvent]:
            try:
                async for message in self._parser.parse(response.aiter_bytes()):
                    event = normalizer.normalize(message)
                    if event is not None:
                        yield event
            finally:
                await stream_context.__aexit__(None, None, None)

        return iterator()

    async def complete(self, request: ChatRequest, model: ModelInfo) -> ChatResponse:
        client = await self._client_manager.get_client()
        payload = self._translator.to_payload(request, model)
        try:
            response = await client.request(
                "POST",
                self._messages_url(),
                headers=self._headers(accept="application/json"),
                json=payload,
                timeout=self._timeout(),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError("OpenRouter timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"OpenRouter request failed: {exc}") from exc

        if response.status_code >= 400:
            message = _provider_error_message(response.content)
            if response.status_code == 401:
                raise ProviderAuthError(message or "OpenRouter authentication failed")
            raise ProviderProtocolError(message or f"OpenRouter returned HTTP {response.status_code}")

        try:
            payload = response.json()
        except Exception as exc:
            raise ProviderProtocolError("invalid upstream JSON response") from exc
        if not isinstance(payload, dict):
            raise ProviderProtocolError("invalid upstream response payload")
        return response_from_payload(payload)

    async def _open_stream(self, stream_context: Any) -> httpx.Response:
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

    def _headers(self, *, accept: str) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
            "Accept": accept,
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


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _int_or_default(value: Any, default: int) -> int:
    return value if isinstance(value, int) else default


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) else None


def _extras(payload: Mapping[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in excluded}


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


def _role_or_default(value: Any):
    from claude_proxy.domain.enums import Role

    try:
        return Role(value)
    except Exception:
        return Role.ASSISTANT
