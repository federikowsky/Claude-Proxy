from __future__ import annotations

import json
from collections.abc import AsyncIterator

import pytest

from llm_proxy.domain.enums import Role
from llm_proxy.domain.errors import ProviderBoundaryError, ProviderProtocolError
from llm_proxy.domain.models import (
    ChatRequest,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    ErrorEvent,
    InputJsonDelta,
    Message,
    MessageDeltaEvent,
    MessageStartEvent,
    MessageStopEvent,
    ModelInfo,
    TextBlock,
    TextDelta,
    ToolChoice,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)
from llm_proxy.infrastructure.providers.openai_compat import (
    OpenAICompatStreamNormalizer,
    OpenAICompatTranslator,
)
from llm_proxy.infrastructure.providers.sse import IncrementalSseParser, SseMessage
from tests.conftest import chunk_bytes, collect_list


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _request(*, stream: bool = True) -> ChatRequest:
    return ChatRequest(
        model="nvidia/llama-3.3-nemotron-super-49b-v1",
        messages=(
            Message(
                role=Role.USER,
                content=(TextBlock(text="Hello"),),
            ),
        ),
        system=(TextBlock(text="You are a helpful assistant."),),
        metadata=None,
        temperature=0.7,
        top_p=0.9,
        max_tokens=128,
        stop_sequences=("STOP",),
        tools=(
            ToolDefinition(
                name="bash",
                description="Run shell commands",
                input_schema={"type": "object", "properties": {"cmd": {"type": "string"}}},
            ),
        ),
        tool_choice=None,
        thinking=None,
        stream=stream,
        extensions={},
    )


def _model(
    *,
    name: str = "nvidia/llama-3.3-nemotron-super-49b-v1",
    provider: str = "nvidia",
) -> ModelInfo:
    return ModelInfo(
        name=name,
        provider=provider,
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=False,
    )


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    for chunk in chunk_bytes(data, 11):
        yield chunk


# ---------------------------------------------------------------------------
# Translator tests
# ---------------------------------------------------------------------------


def test_translator_maps_full_request_payload() -> None:
    translator = OpenAICompatTranslator("nvidia")
    payload = translator.to_payload(_request(), _model())

    assert payload["model"] == "nvidia/llama-3.3-nemotron-super-49b-v1"
    assert payload["max_tokens"] == 128
    assert payload["stream"] is True
    assert payload["stream_options"] == {"include_usage": True}
    assert payload["temperature"] == 0.7
    assert payload["top_p"] == 0.9
    assert payload["stop"] == ["STOP"]

    # System message is first
    messages = payload["messages"]
    assert messages[0] == {"role": "system", "content": "You are a helpful assistant."}
    assert messages[1]["role"] == "user"
    assert messages[1]["content"] == "Hello"


def test_translator_non_stream_omits_stream_options() -> None:
    translator = OpenAICompatTranslator("gemini")
    payload = translator.to_payload(_request(stream=False), _model(provider="gemini"))
    assert payload["stream"] is False
    assert "stream_options" not in payload


def test_translator_converts_tools_to_function_format() -> None:
    translator = OpenAICompatTranslator("nvidia")
    payload = translator.to_payload(_request(), _model())
    tools = payload["tools"]
    assert len(tools) == 1
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "bash"
    assert tools[0]["function"]["description"] == "Run shell commands"
    assert tools[0]["function"]["parameters"] == {
        "type": "object",
        "properties": {"cmd": {"type": "string"}},
    }


def test_translator_tool_choice_auto() -> None:
    translator = OpenAICompatTranslator("nvidia")
    request = ChatRequest(
        model="test",
        messages=(Message(role=Role.USER, content=(TextBlock(text="hi"),)),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=(ToolDefinition(name="t", description=None, input_schema={"type": "object"}),),
        tool_choice=ToolChoice(type="auto"),
        thinking=None,
        stream=True,
        extensions={},
    )
    payload = translator.to_payload(request, _model())
    assert payload["tool_choice"] == "auto"


def test_translator_tool_choice_any_maps_to_required() -> None:
    translator = OpenAICompatTranslator("nvidia")
    request = ChatRequest(
        model="test",
        messages=(Message(role=Role.USER, content=(TextBlock(text="hi"),)),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=(ToolDefinition(name="t", description=None, input_schema={"type": "object"}),),
        tool_choice=ToolChoice(type="any"),
        thinking=None,
        stream=True,
        extensions={},
    )
    payload = translator.to_payload(request, _model())
    assert payload["tool_choice"] == "required"


def test_translator_tool_choice_specific_tool() -> None:
    translator = OpenAICompatTranslator("nvidia")
    request = ChatRequest(
        model="test",
        messages=(Message(role=Role.USER, content=(TextBlock(text="hi"),)),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=(ToolDefinition(name="bash", description=None, input_schema={"type": "object"}),),
        tool_choice=ToolChoice(type="tool", name="bash"),
        thinking=None,
        stream=True,
        extensions={},
    )
    payload = translator.to_payload(request, _model())
    assert payload["tool_choice"] == {"type": "function", "function": {"name": "bash"}}


def test_translator_tool_use_block_in_assistant_message() -> None:
    translator = OpenAICompatTranslator("nvidia")
    request = ChatRequest(
        model="test",
        messages=(
            Message(role=Role.USER, content=(TextBlock(text="run ls"),)),
            Message(
                role=Role.ASSISTANT,
                content=(
                    TextBlock(text="Running:"),
                    ToolUseBlock(id="call_1", name="bash", input={"cmd": "ls"}),
                ),
            ),
            Message(
                role=Role.USER,
                content=(ToolResultBlock(tool_use_id="call_1", content="file.txt"),),
            ),
        ),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=(ToolDefinition(name="bash", description=None, input_schema={"type": "object"}),),
        tool_choice=None,
        thinking=None,
        stream=True,
        extensions={},
    )
    payload = translator.to_payload(request, _model())
    messages = payload["messages"]

    # Assistant message with text + tool_call
    assistant_msg = messages[1]
    assert assistant_msg["role"] == "assistant"
    assert assistant_msg["content"] == "Running:"
    assert len(assistant_msg["tool_calls"]) == 1
    tc = assistant_msg["tool_calls"][0]
    assert tc["id"] == "call_1"
    assert tc["type"] == "function"
    assert tc["function"]["name"] == "bash"
    assert json.loads(tc["function"]["arguments"]) == {"cmd": "ls"}

    # Tool result → role=tool
    tool_msg = messages[2]
    assert tool_msg["role"] == "tool"
    assert tool_msg["tool_call_id"] == "call_1"
    assert tool_msg["content"] == "file.txt"


def test_translator_rejects_empty_input_schema() -> None:
    translator = OpenAICompatTranslator("nvidia")
    request = ChatRequest(
        model="test",
        messages=(Message(role=Role.USER, content=(TextBlock(text="hi"),)),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=64,
        stop_sequences=(),
        tools=(ToolDefinition(name="bad", description=None, input_schema={}),),
        tool_choice=None,
        thinking=None,
        stream=True,
        extensions={},
    )
    with pytest.raises(ProviderBoundaryError):
        translator.to_payload(request, _model())


def test_translator_optional_fields_omitted_when_none() -> None:
    request = ChatRequest(
        model="test",
        messages=(Message(role=Role.USER, content=(TextBlock(text="hi"),)),),
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
        extensions={},
    )
    translator = OpenAICompatTranslator("nvidia")
    payload = translator.to_payload(request, _model())

    assert "temperature" not in payload
    assert "top_p" not in payload
    assert "stop" not in payload
    assert "tools" not in payload
    assert "tool_choice" not in payload


# ---------------------------------------------------------------------------
# StreamNormalizer tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_normalizer_basic_text_flow() -> None:
    upstream = (
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"content":"Hello"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"content":" world"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-1","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{},"finish_reason":"stop"}],'
        b'"usage":{"prompt_tokens":10,"completion_tokens":5,"total_tokens":15}}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    assert isinstance(events[0], MessageStartEvent)
    assert events[0].message.id == "chatcmpl-1"
    assert events[0].message.model == "test"

    assert isinstance(events[1], ContentBlockStartEvent)
    assert isinstance(events[1].block, TextBlock)
    assert events[1].index == 0

    assert isinstance(events[2], ContentBlockDeltaEvent)
    assert isinstance(events[2].delta, TextDelta)
    assert events[2].delta.text == "Hello"

    assert isinstance(events[3], ContentBlockDeltaEvent)
    assert events[3].delta.text == " world"

    # finish → block stop + message_delta
    assert isinstance(events[4], ContentBlockStopEvent)
    assert isinstance(events[5], MessageDeltaEvent)
    assert events[5].stop_reason == "end_turn"

    assert isinstance(events[-1], MessageStopEvent)


@pytest.mark.asyncio
async def test_stream_normalizer_tool_calls_flow() -> None:
    upstream = (
        b'data: {"id":"chatcmpl-2","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-2","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1",'
        b'"type":"function","function":{"name":"bash","arguments":""}}]},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-2","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":'
        b'{"arguments":"{\\"cmd\\":"}}]},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-2","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"function":'
        b'{"arguments":"\\"ls\\"}"}}]},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-2","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    # message_start
    assert isinstance(events[0], MessageStartEvent)

    # tool block start
    tool_starts = [e for e in events if isinstance(e, ContentBlockStartEvent)]
    assert len(tool_starts) == 1
    assert isinstance(tool_starts[0].block, ToolUseBlock)
    assert tool_starts[0].block.name == "bash"
    assert tool_starts[0].block.id == "call_1"

    # JSON deltas
    json_deltas = [
        e for e in events
        if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, InputJsonDelta)
    ]
    assert len(json_deltas) == 2
    accumulated = "".join(d.delta.partial_json for d in json_deltas)
    assert json.loads(accumulated) == {"cmd": "ls"}

    # finish_reason=tool_calls → stop_reason=tool_use
    msg_deltas = [e for e in events if isinstance(e, MessageDeltaEvent)]
    assert any(d.stop_reason == "tool_use" for d in msg_deltas)

    assert isinstance(events[-1], MessageStopEvent)


@pytest.mark.asyncio
async def test_stream_normalizer_usage_only_chunk() -> None:
    upstream = (
        b'data: {"id":"chatcmpl-3","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{"role":"assistant","content":"Hi"},"finish_reason":null}]}\n\n'
        b'data: {"id":"chatcmpl-3","object":"chat.completion.chunk","model":"test",'
        b'"choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b'data: {"id":"chatcmpl-3","object":"chat.completion.chunk","model":"test",'
        b'"choices":[],"usage":{"prompt_tokens":8,"completion_tokens":2,"total_tokens":10}}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    # The separate usage chunk should produce a MessageDeltaEvent with usage
    usage_deltas = [
        e for e in events
        if isinstance(e, MessageDeltaEvent) and e.usage is not None
    ]
    assert len(usage_deltas) >= 1
    assert usage_deltas[-1].usage.input_tokens == 8
    assert usage_deltas[-1].usage.output_tokens == 2


@pytest.mark.asyncio
async def test_stream_normalizer_error_event() -> None:
    upstream = (
        b'data: {"error":{"message":"Rate limit exceeded","type":"rate_limit_error"}}\n\n'
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "Rate limit exceeded" in events[0].message


def test_stream_normalizer_done_sentinel() -> None:
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = normalizer.normalize(SseMessage(event="", data="[DONE]"))
    assert isinstance(events[-1], MessageStopEvent)


def test_stream_normalizer_invalid_json_raises() -> None:
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    with pytest.raises(ProviderProtocolError):
        normalizer.normalize(SseMessage(event="", data="not json"))


def test_stream_normalizer_finish_reason_mapping() -> None:
    """All known finish_reason values get mapped correctly."""
    normalizer = OpenAICompatStreamNormalizer("nvidia")

    # First prime message_started flag
    start_msg = SseMessage(
        event="",
        data='{"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}',
    )
    normalizer.normalize(start_msg)

    cases = {
        "stop": "end_turn",
        "length": "max_tokens",
        "tool_calls": "tool_use",
        "content_filter": "end_turn",
    }
    for finish_reason, expected_stop_reason in cases.items():
        norm = OpenAICompatStreamNormalizer("nvidia")
        norm.normalize(start_msg)
        events = norm.normalize(SseMessage(
            event="",
            data=json.dumps({
                "id": "c",
                "model": "m",
                "choices": [{"index": 0, "delta": {}, "finish_reason": finish_reason}],
            }),
        ))
        msg_deltas = [e for e in events if isinstance(e, MessageDeltaEvent)]
        assert msg_deltas[0].stop_reason == expected_stop_reason, (
            f"finish_reason={finish_reason!r}: expected {expected_stop_reason!r}"
        )


@pytest.mark.asyncio
async def test_stream_normalizer_text_then_tool_blocks() -> None:
    """Text block is properly closed before tool call block starts."""
    upstream = (
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"Let me run that."},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"bash","arguments":"{\\"cmd\\":\\"ls\\"}"}}]},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    # Text block: start at index 0, delta, stop
    assert isinstance(events[1], ContentBlockStartEvent)
    assert isinstance(events[1].block, TextBlock)
    assert events[1].index == 0

    # Text block closed before tool starts
    stops_before_tool = [
        i for i, e in enumerate(events) if isinstance(e, ContentBlockStopEvent) and e.index == 0
    ]
    tool_starts = [
        i for i, e in enumerate(events) if isinstance(e, ContentBlockStartEvent) and isinstance(e.block, ToolUseBlock)
    ]
    assert stops_before_tool[0] < tool_starts[0]

    # Tool block at index 1
    assert tool_starts[0] is not None
    tool_event = events[tool_starts[0]]
    assert tool_event.index == 1
