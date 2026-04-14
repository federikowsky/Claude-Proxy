from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from typing import Any

import httpx

from claude_proxy.domain.enums import Role
from claude_proxy.domain.errors import (
    ProviderAuthError,
    ProviderBoundaryError,
    ProviderHttpError,
    ProviderProtocolError,
    UpstreamTimeoutError,
)
from claude_proxy.domain.models import (
    CanonicalEvent,
    ChatRequest,
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
    ModelInfo,
    ProviderRequestContext,
    ProviderWarningEvent,
    TextBlock,
    TextDelta,
    ToolUseBlock,
    Usage,
)
from claude_proxy.infrastructure.config import ProviderSettings
from claude_proxy.infrastructure.http import SharedAsyncClientManager
from claude_proxy.infrastructure.providers.sse import IncrementalSseParser, SseMessage
from claude_proxy.jsonutil import json_loads

_logger = logging.getLogger("claude_proxy.openai_compat")

# ---------------------------------------------------------------------------
# Stop reason mapping: OpenAI finish_reason → Anthropic stop_reason
# ---------------------------------------------------------------------------
_FINISH_REASON_MAP: dict[str, str] = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "end_turn",
    "function_call": "tool_use",
}


class OpenAICompatTranslator:
    """Translates Anthropic-canonical ChatRequest → OpenAI Chat Completions payload."""

    def __init__(self, provider_name: str = "openai_compat") -> None:
        self._provider_name = provider_name

    def to_payload(self, request: ChatRequest, model: ModelInfo) -> dict[str, object]:
        for tool in request.tools:
            schema = tool.input_schema
            if not isinstance(schema, Mapping) or not schema:
                raise ProviderBoundaryError(
                    f"provider boundary invariant: tool '{tool.name}' has invalid "
                    f"input_schema — cannot emit to provider",
                    details={"tool": tool.name, "schema": repr(schema)},
                )

        messages: list[dict[str, object]] = []
        if request.system:
            system_text = " ".join(
                block.text for block in request.system if isinstance(block, TextBlock)
            )
            if system_text:
                messages.append({"role": "system", "content": system_text})

        for message in request.messages:
            messages.append(self._convert_message(message))

        payload: dict[str, object] = {
            "model": model.name,
            "messages": messages,
            "max_tokens": request.max_tokens,
            "stream": request.stream,
        }
        if request.stream:
            payload["stream_options"] = {"include_usage": True}
        if request.temperature is not None:
            payload["temperature"] = request.temperature
        if request.top_p is not None:
            payload["top_p"] = request.top_p
        if request.stop_sequences:
            payload["stop"] = list(request.stop_sequences)
        if request.tools:
            payload["tools"] = [self._convert_tool(tool) for tool in request.tools]
        if request.tool_choice is not None:
            payload["tool_choice"] = self._convert_tool_choice(request.tool_choice)
        return payload

    def _convert_message(self, message: Message) -> dict[str, object]:
        from claude_proxy.domain.models import Message, ToolResultBlock

        role = message.role.value

        # Tool result messages → OpenAI "tool" role
        if len(message.content) == 1 and isinstance(message.content[0], ToolResultBlock):
            block = message.content[0]
            content_str = block.content if isinstance(block.content, str) else ""
            return {
                "role": "tool",
                "tool_call_id": block.tool_use_id,
                "content": content_str,
            }

        # Collect text and tool_calls from content blocks
        text_parts: list[str] = []
        tool_calls: list[dict[str, object]] = []
        for block in message.content:
            if isinstance(block, TextBlock):
                text_parts.append(block.text)
            elif isinstance(block, ToolUseBlock):
                tool_calls.append({
                    "id": block.id,
                    "type": "function",
                    "function": {
                        "name": block.name,
                        "arguments": json.dumps(block.input) if not isinstance(block.input, str) else block.input,
                    },
                })

        result: dict[str, object] = {"role": role}
        if text_parts:
            result["content"] = " ".join(text_parts)
        elif not tool_calls:
            result["content"] = ""
        if tool_calls:
            result["tool_calls"] = tool_calls
        return result

    def _convert_tool(self, tool: ToolDefinition) -> dict[str, object]:
        from claude_proxy.domain.models import ToolDefinition

        func: dict[str, object] = {"name": tool.name}
        if tool.description is not None:
            func["description"] = tool.description
        func["parameters"] = dict(tool.input_schema)
        return {"type": "function", "function": func}

    def _convert_tool_choice(self, choice: ToolChoice) -> object:
        from claude_proxy.domain.models import ToolChoice

        if choice.type == "auto":
            return "auto"
        if choice.type == "any":
            return "required"
        if choice.type == "tool" and choice.name:
            return {"type": "function", "function": {"name": choice.name}}
        return "auto"


class OpenAICompatStreamNormalizer:
    """Translates OpenAI Chat Completions SSE chunks → Anthropic canonical events.

    Synthesizes the Anthropic event sequence (message_start, content_block_start,
    content_block_delta, content_block_stop, message_delta, message_stop) from
    the flat OpenAI chunk stream.
    """

    def __init__(self, provider_name: str = "openai_compat") -> None:
        self._provider_name = provider_name
        self._message_started: bool = False
        self._stream_finished: bool = False
        self._current_block_index: int = -1
        self._block_open: bool = False
        self._tool_call_blocks: dict[int, _ToolCallAccumulator] = {}
        self._msg_id: str = ""
        self._model: str = ""

    def normalize(self, message: SseMessage) -> list[CanonicalEvent]:
        if message.data == "[DONE]":
            return self._finalize()

        try:
            payload = json_loads(message.data)
        except Exception as exc:
            raise ProviderProtocolError("invalid upstream JSON event") from exc
        if not isinstance(payload, dict):
            raise ProviderProtocolError("invalid upstream event payload")

        # Error response in stream
        if payload.get("error"):
            error = payload["error"]
            msg = error.get("message", "provider error") if isinstance(error, dict) else str(error)
            return [ErrorEvent(message=msg, error_type="provider_error")]

        events: list[CanonicalEvent] = []
        self._msg_id = self._msg_id or _string(payload.get("id"))
        self._model = self._model or _string(payload.get("model"))

        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            # Usage-only chunk (no choices) — extract usage for message_delta
            usage_payload = payload.get("usage")
            if isinstance(usage_payload, dict):
                events.append(MessageDeltaEvent(
                    usage=_usage_from_openai(usage_payload),
                ))
            return events

        choice = choices[0]
        delta = choice.get("delta", {})
        finish_reason = choice.get("finish_reason")

        if not self._message_started:
            events.append(self._emit_message_start(payload))
            self._message_started = True

        # Text content
        content = delta.get("content")
        if isinstance(content, str) and content:
            if not self._block_open:
                self._current_block_index += 1
                events.append(ContentBlockStartEvent(
                    index=self._current_block_index,
                    block=TextBlock(text=""),
                ))
                self._block_open = True
            events.append(ContentBlockDeltaEvent(
                index=self._current_block_index,
                delta=TextDelta(text=content),
            ))

        # Tool calls
        tool_calls = delta.get("tool_calls")
        if isinstance(tool_calls, list):
            for tc in tool_calls:
                tc_events = self._handle_tool_call_delta(tc)
                events.extend(tc_events)

        # Finish reason → close blocks + message_delta
        if finish_reason is not None:
            events.extend(self._emit_finish(finish_reason, payload))

        return events

    def _emit_message_start(self, payload: dict[str, Any]) -> MessageStartEvent:
        usage_payload = payload.get("usage") or {}
        return MessageStartEvent(
            message=ChatResponse(
                id=self._msg_id,
                role=Role.ASSISTANT,
                model=self._model,
                content=(),
                stop_reason=None,
                stop_sequence=None,
                usage=_usage_from_openai(usage_payload) if usage_payload else Usage(),
            ),
        )

    def _handle_tool_call_delta(self, tc: dict[str, Any]) -> list[CanonicalEvent]:
        events: list[CanonicalEvent] = []
        tc_index = tc.get("index", 0)

        if tc_index not in self._tool_call_blocks:
            # Close any open text block first
            if self._block_open:
                events.append(ContentBlockStopEvent(index=self._current_block_index))
                self._block_open = False

            self._current_block_index += 1
            tc_id = tc.get("id", f"call_{tc_index}")
            func = tc.get("function", {})
            name = func.get("name", "")
            self._tool_call_blocks[tc_index] = _ToolCallAccumulator(
                block_index=self._current_block_index,
                tool_id=tc_id,
                name=name,
            )
            events.append(ContentBlockStartEvent(
                index=self._current_block_index,
                block=ToolUseBlock(id=tc_id, name=name, input={}),
            ))
            self._block_open = True

        acc = self._tool_call_blocks[tc_index]
        func = tc.get("function", {})
        args_chunk = func.get("arguments", "")
        if args_chunk:
            events.append(ContentBlockDeltaEvent(
                index=acc.block_index,
                delta=InputJsonDelta(partial_json=args_chunk),
            ))

        return events

    def _emit_finish(self, finish_reason: str, payload: dict[str, Any]) -> list[CanonicalEvent]:
        events: list[CanonicalEvent] = []
        # Close any open block
        if self._block_open:
            events.append(ContentBlockStopEvent(index=self._current_block_index))
            self._block_open = False

        stop_reason = _FINISH_REASON_MAP.get(finish_reason, finish_reason)
        usage_payload = payload.get("usage")
        events.append(MessageDeltaEvent(
            stop_reason=stop_reason,
            usage=_usage_from_openai(usage_payload) if isinstance(usage_payload, dict) else None,
        ))
        return events

    def _finalize(self) -> list[CanonicalEvent]:
        events: list[CanonicalEvent] = []
        if self._block_open:
            events.append(ContentBlockStopEvent(index=self._current_block_index))
            self._block_open = False
        if not self._stream_finished:
            self._stream_finished = True
            events.append(MessageStopEvent())
        return events


class OpenAICompatProvider:
    """Provider for OpenAI Chat Completions compatible APIs (NVIDIA NIM, Gemini, etc.)."""

    def __init__(
        self,
        *,
        settings: ProviderSettings,
        client_manager: SharedAsyncClientManager,
        translator: OpenAICompatTranslator | None = None,
        parser: IncrementalSseParser | None = None,
        provider_name: str = "openai_compat",
    ) -> None:
        self._settings = settings
        self._client_manager = client_manager
        self._provider_name = provider_name
        self._translator = translator or OpenAICompatTranslator(provider_name)
        self._parser = parser or IncrementalSseParser()

    async def stream(
        self,
        request: ChatRequest,
        model: ModelInfo,
        provider_context: ProviderRequestContext | None = None,
    ) -> AsyncIterator[CanonicalEvent]:
        client = await self._client_manager.get_client()
        payload = self._translator.to_payload(request, model)
        stream_context = client.stream(
            "POST",
            self._completions_url(),
            headers=self._headers(accept="text/event-stream", provider_context=provider_context),
            json=payload,
            timeout=self._timeout(),
        )
        response = await self._open_stream(stream_context)
        normalizer = OpenAICompatStreamNormalizer(self._provider_name)

        async def iterator() -> AsyncIterator[CanonicalEvent]:
            try:
                async for message in self._parser.parse(response.aiter_bytes()):
                    events = normalizer.normalize(message)
                    for event in events:
                        yield event
            finally:
                await stream_context.__aexit__(None, None, None)

        return iterator()

    async def complete(
        self,
        request: ChatRequest,
        model: ModelInfo,
        provider_context: ProviderRequestContext | None = None,
    ) -> ChatResponse:
        client = await self._client_manager.get_client()
        payload = self._translator.to_payload(request, model)
        try:
            response = await client.request(
                "POST",
                self._completions_url(),
                headers=self._headers(accept="application/json", provider_context=provider_context),
                json=payload,
                timeout=self._timeout(),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(f"{self._provider_name} timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"{self._provider_name} request failed: {exc}") from exc

        if response.status_code >= 400:
            self._raise_http_error(response.status_code, response.content)

        try:
            data = response.json()
        except Exception as exc:
            raise ProviderProtocolError("invalid upstream JSON response") from exc
        if not isinstance(data, dict):
            raise ProviderProtocolError("invalid upstream response payload")
        return _response_from_openai(data)

    async def count_tokens(
        self,
        request: ChatRequest,
        model: ModelInfo,
        provider_context: ProviderRequestContext | None = None,
    ) -> int:
        # OpenAI-compatible APIs generally lack a native count_tokens endpoint.
        # Use a minimal completion probe with max_tokens=1 to extract usage.
        client = await self._client_manager.get_client()
        probe_payload = self._translator.to_payload(request, model)
        probe_payload["stream"] = False
        probe_payload["max_tokens"] = 1
        probe_payload.pop("stream_options", None)
        try:
            response = await client.request(
                "POST",
                self._completions_url(),
                headers=self._headers(accept="application/json", provider_context=provider_context),
                json=probe_payload,
                timeout=self._timeout(),
            )
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(f"{self._provider_name} timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"{self._provider_name} request failed: {exc}") from exc

        if response.status_code >= 400:
            self._raise_http_error(response.status_code, response.content)

        try:
            data = response.json()
        except Exception as exc:
            raise ProviderProtocolError("invalid upstream JSON response") from exc
        if not isinstance(data, dict):
            raise ProviderProtocolError("invalid upstream response payload")
        usage = data.get("usage", {})
        prompt_tokens = usage.get("prompt_tokens")
        if not isinstance(prompt_tokens, int):
            raise ProviderProtocolError("missing prompt_tokens in count probe response")
        return prompt_tokens

    async def _open_stream(self, stream_context: Any) -> httpx.Response:
        try:
            response = await stream_context.__aenter__()
        except httpx.TimeoutException as exc:
            raise UpstreamTimeoutError(f"{self._provider_name} timed out") from exc
        except httpx.HTTPError as exc:
            raise ProviderProtocolError(f"{self._provider_name} request failed: {exc}") from exc

        if response.status_code >= 400:
            body = await response.aread()
            await stream_context.__aexit__(None, None, None)
            self._raise_http_error(response.status_code, body)
        return response

    def _completions_url(self) -> str:
        return f"{self._settings.base_url.rstrip('/')}/chat/completions"

    def _headers(
        self,
        *,
        accept: str,
        provider_context: ProviderRequestContext | None = None,
    ) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._settings.api_key.get_secret_value()}",
            "Accept": accept,
            "Content-Type": "application/json",
        }
        if self._settings.debug_echo_upstream_body:
            headers["X-Debug"] = "1"
        if provider_context is not None:
            headers.update(provider_context.headers)
        return headers

    def _timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=self._settings.connect_timeout_seconds,
            read=self._settings.read_timeout_seconds,
            write=self._settings.write_timeout_seconds,
            pool=self._settings.pool_timeout_seconds,
        )

    def _raise_http_error(self, status: int, body: bytes) -> None:
        message = _provider_error_message(body)
        if status in {401, 403}:
            raise ProviderAuthError(
                message or f"{self._provider_name} authentication failed",
                details={
                    "provider": self._provider_name,
                    "upstream_status": status,
                },
            )
        raise ProviderHttpError(
            message or f"{self._provider_name} returned HTTP {status}",
            upstream_status=status,
            provider=self._provider_name,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ToolCallAccumulator:
    __slots__ = ("block_index", "tool_id", "name")

    def __init__(self, *, block_index: int, tool_id: str, name: str) -> None:
        self.block_index = block_index
        self.tool_id = tool_id
        self.name = name


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _usage_from_openai(usage: dict[str, Any]) -> Usage:
    return Usage(
        input_tokens=usage.get("prompt_tokens") if isinstance(usage.get("prompt_tokens"), int) else None,
        output_tokens=usage.get("completion_tokens") if isinstance(usage.get("completion_tokens"), int) else None,
        reasoning_tokens=(
            usage.get("completion_tokens_details", {}).get("reasoning_tokens")
            if isinstance(usage.get("completion_tokens_details"), dict)
            else None
        ),
    )


def _response_from_openai(data: dict[str, Any]) -> ChatResponse:
    """Convert an OpenAI Chat Completions JSON response to a canonical ChatResponse."""
    choices = data.get("choices", [])
    if not isinstance(choices, list) or not choices:
        raise ProviderProtocolError("missing choices in response")
    choice = choices[0]
    message = choice.get("message", {})
    finish_reason = choice.get("finish_reason", "stop")

    content_blocks: list[ContentBlock] = []
    text = message.get("content")
    if isinstance(text, str) and text:
        content_blocks.append(TextBlock(text=text))

    tool_calls = message.get("tool_calls")
    if isinstance(tool_calls, list):
        for tc in tool_calls:
            func = tc.get("function", {})
            args_str = func.get("arguments", "{}")
            try:
                args = json_loads(args_str)
            except Exception:
                args = args_str
            content_blocks.append(ToolUseBlock(
                id=tc.get("id", ""),
                name=func.get("name", ""),
                input=args,
            ))

    usage_payload = data.get("usage", {})
    return ChatResponse(
        id=_string(data.get("id")),
        role=Role.ASSISTANT,
        model=_string(data.get("model")),
        content=tuple(content_blocks),
        stop_reason=_FINISH_REASON_MAP.get(finish_reason, finish_reason),
        stop_sequence=None,
        usage=_usage_from_openai(usage_payload) if isinstance(usage_payload, dict) else Usage(),
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
