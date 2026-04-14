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
    ThinkingBlock,
    ThinkingDelta,
    ToolChoice,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)
from llm_proxy.infrastructure.providers.openai_compat import (
    OpenAICompatStreamNormalizer,
    OpenAICompatTranslator,
    _ThinkingTagParser,
    _parse_thinking_tags,
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


# ---------------------------------------------------------------------------
# ThinkingTagParser unit tests
# ---------------------------------------------------------------------------


class TestThinkingTagParser:
    def test_plain_text_no_tags(self) -> None:
        parser = _ThinkingTagParser()
        assert parser.feed("hello world") == [("text", "hello world")]

    def test_full_think_block(self) -> None:
        parser = _ThinkingTagParser()
        segments = parser.feed("<think>reasoning here</think>answer")
        assert segments == [
            ("thinking", "reasoning here"),
            ("text", "answer"),
        ]

    def test_think_block_split_across_chunks(self) -> None:
        parser = _ThinkingTagParser()
        s1 = parser.feed("<thi")
        # Partial open tag buffered — nothing emitted
        assert s1 == []
        s2 = parser.feed("nk>deep thought</think>result")
        assert ("thinking", "deep thought") in s2
        assert ("text", "result") in s2

    def test_unclosed_think_tag(self) -> None:
        parser = _ThinkingTagParser()
        segments = parser.feed("<think>still thinking")
        assert segments == [("thinking", "still thinking")]
        assert parser.in_thinking is True
        flushed = parser.flush()
        assert flushed == []

    def test_multiple_think_blocks(self) -> None:
        parser = _ThinkingTagParser()
        segments = parser.feed("<think>a</think>text<think>b</think>end")
        assert segments == [
            ("thinking", "a"),
            ("text", "text"),
            ("thinking", "b"),
            ("text", "end"),
        ]

    def test_flush_emits_buffered_partial_tag(self) -> None:
        parser = _ThinkingTagParser()
        # Feed text where close tag is partially buffered
        segments = parser.feed("<think>thought</thi")
        assert ("thinking", "thought") in segments
        # The partial "</thi" is buffered — flush drains it
        flushed = parser.flush()
        assert flushed == [("thinking", "</thi")]

    def test_partial_close_tag_buffered(self) -> None:
        parser = _ThinkingTagParser()
        parser.feed("<think>thought</thi")
        assert parser.in_thinking is True
        s = parser.feed("nk>done")
        assert ("text", "done") in s


# ---------------------------------------------------------------------------
# _parse_thinking_tags (non-streaming) tests
# ---------------------------------------------------------------------------


class TestParseThinkingTags:
    def test_no_tags(self) -> None:
        blocks = _parse_thinking_tags("just text")
        assert len(blocks) == 1
        assert isinstance(blocks[0], TextBlock)
        assert blocks[0].text == "just text"

    def test_think_then_text(self) -> None:
        blocks = _parse_thinking_tags("<think>reason</think>answer")
        assert len(blocks) == 2
        assert isinstance(blocks[0], ThinkingBlock)
        assert blocks[0].thinking == "reason"
        assert isinstance(blocks[1], TextBlock)
        assert blocks[1].text == "answer"

    def test_unclosed_think_tag(self) -> None:
        blocks = _parse_thinking_tags("<think>forever thinking")
        assert len(blocks) == 1
        assert isinstance(blocks[0], ThinkingBlock)
        assert blocks[0].thinking == "forever thinking"


# ---------------------------------------------------------------------------
# Stream normalizer: thinking via <think> tags
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stream_normalizer_think_tags_in_text() -> None:
    """<think> tags in text content are converted to ThinkingBlock/ThinkingDelta."""
    upstream = (
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"<think>let me think</think>"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"hello!"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    # Find thinking block
    thinking_starts = [
        e for e in events if isinstance(e, ContentBlockStartEvent) and isinstance(e.block, ThinkingBlock)
    ]
    assert len(thinking_starts) == 1

    thinking_deltas = [
        e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, ThinkingDelta)
    ]
    assert any(d.delta.thinking == "let me think" for d in thinking_deltas)

    # Find text block
    text_starts = [
        e for e in events if isinstance(e, ContentBlockStartEvent) and isinstance(e.block, TextBlock)
    ]
    assert len(text_starts) == 1

    text_deltas = [
        e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
    ]
    assert any(d.delta.text == "hello!" for d in text_deltas)


@pytest.mark.asyncio
async def test_stream_normalizer_reasoning_content_field() -> None:
    """reasoning_content from delta is emitted as ThinkingBlock/ThinkingDelta."""
    upstream = (
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"reasoning_content":"step 1..."},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"answer"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    thinking_deltas = [
        e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, ThinkingDelta)
    ]
    assert len(thinking_deltas) == 1
    assert thinking_deltas[0].delta.thinking == "step 1..."

    text_deltas = [
        e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
    ]
    assert len(text_deltas) == 1
    assert text_deltas[0].delta.text == "answer"


@pytest.mark.asyncio
async def test_stream_normalizer_think_tags_across_chunks() -> None:
    """<think> tags split across multiple SSE chunks are handled correctly."""
    upstream = (
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant","content":""},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"<think>first part"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":" second part</think>"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"visible text"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    thinking_deltas = [
        e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, ThinkingDelta)
    ]
    combined_thinking = "".join(d.delta.thinking for d in thinking_deltas)
    assert combined_thinking == "first part second part"

    text_deltas = [
        e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
    ]
    combined_text = "".join(d.delta.text for d in text_deltas)
    assert combined_text == "visible text"


@pytest.mark.asyncio
async def test_stream_normalizer_thinking_then_tool_call() -> None:
    """Thinking block is properly closed before tool call starts."""
    upstream = (
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"<think>plan</think>"},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"tool_calls":[{"index":0,"id":"call_1","type":"function","function":{"name":"bash","arguments":"{\\"cmd\\":\\"ls\\"}"}}]},"finish_reason":null}]}\n\n'
        b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"tool_calls"}]}\n\n'
        b"data: [DONE]\n\n"
    )
    parser = IncrementalSseParser()
    normalizer = OpenAICompatStreamNormalizer("nvidia")
    events = []
    async for message in parser.parse(_chunks(upstream)):
        events.extend(normalizer.normalize(message))

    thinking_starts = [
        e for e in events if isinstance(e, ContentBlockStartEvent) and isinstance(e.block, ThinkingBlock)
    ]
    assert len(thinking_starts) == 1

    tool_starts = [
        e for e in events if isinstance(e, ContentBlockStartEvent) and isinstance(e.block, ToolUseBlock)
    ]
    assert len(tool_starts) == 1

    # Thinking block closed before tool block opens
    thinking_stop_idx = next(
        i for i, e in enumerate(events)
        if isinstance(e, ContentBlockStopEvent) and e.index == thinking_starts[0].index
    )
    tool_start_idx = next(i for i, e in enumerate(events) if e is tool_starts[0])
    assert thinking_stop_idx < tool_start_idx


# ---------------------------------------------------------------------------
# Configurable extraction tests (Phase 08-02)
# ---------------------------------------------------------------------------


class TestThinkingTagParserCustomTags:
    """_ThinkingTagParser with non-default open/close tags."""

    def test_custom_tags_basic(self) -> None:
        parser = _ThinkingTagParser("<reasoning>", "</reasoning>")
        segments = parser.feed("hello<reasoning>deep thought</reasoning>world")
        assert segments == [("text", "hello"), ("thinking", "deep thought"), ("text", "world")]

    def test_custom_tags_flush(self) -> None:
        parser = _ThinkingTagParser("<r>", "</r>")
        segments = parser.feed("before<r>thinking")
        assert ("thinking", "thinking") in segments
        remaining = parser.flush()
        assert remaining == []

    def test_default_tags_unchanged(self) -> None:
        parser = _ThinkingTagParser()
        segments = parser.feed("hello<think>deep</think>world")
        assert segments == [("text", "hello"), ("thinking", "deep"), ("text", "world")]


class TestParseThinkingTagsCustom:
    """_parse_thinking_tags with custom tag parameters."""

    def test_custom_tags(self) -> None:
        blocks = _parse_thinking_tags("before<r>thought</r>after", "<r>", "</r>")
        assert len(blocks) == 3
        assert isinstance(blocks[0], TextBlock) and blocks[0].text == "before"
        assert isinstance(blocks[1], ThinkingBlock) and blocks[1].thinking == "thought"
        assert isinstance(blocks[2], TextBlock) and blocks[2].text == "after"

    def test_unclosed_custom_tag(self) -> None:
        blocks = _parse_thinking_tags("start<reason>partial", "<reason>", "</reason>")
        assert len(blocks) == 2
        assert isinstance(blocks[0], TextBlock) and blocks[0].text == "start"
        assert isinstance(blocks[1], ThinkingBlock) and blocks[1].thinking == "partial"

    def test_default_tags_backward_compat(self) -> None:
        blocks = _parse_thinking_tags("a<think>b</think>c")
        assert len(blocks) == 3


class TestNormalizerNullThinkingTags:
    """Normalizer with thinking_open_tag=None disables tag parsing."""

    @pytest.mark.asyncio
    async def test_null_tags_passes_text_through(self) -> None:
        upstream = (
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"<think>raw tags</think> visible"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        parser = IncrementalSseParser()
        normalizer = OpenAICompatStreamNormalizer("test", thinking_open_tag=None)
        events = []
        async for message in parser.parse(_chunks(upstream)):
            events.extend(normalizer.normalize(message))

        text_deltas = [
            e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
        ]
        combined = "".join(d.delta.text for d in text_deltas)
        assert "<think>raw tags</think> visible" == combined

        thinking_deltas = [
            e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, ThinkingDelta)
        ]
        assert len(thinking_deltas) == 0


class TestNormalizerCustomExtractionFields:
    """Normalizer with custom thinking_extraction_fields."""

    @pytest.mark.asyncio
    async def test_custom_field_name(self) -> None:
        upstream = (
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"thought":"deep reason"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"answer"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        parser = IncrementalSseParser()
        normalizer = OpenAICompatStreamNormalizer(
            "test",
            thinking_extraction_fields=("thought",),
        )
        events = []
        async for message in parser.parse(_chunks(upstream)):
            events.extend(normalizer.normalize(message))

        thinking_deltas = [
            e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, ThinkingDelta)
        ]
        assert len(thinking_deltas) > 0
        assert thinking_deltas[0].delta.thinking == "deep reason"

    @pytest.mark.asyncio
    async def test_empty_extraction_fields_skips_reasoning(self) -> None:
        upstream = (
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"reasoning_content":"ignored","content":"text"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        parser = IncrementalSseParser()
        normalizer = OpenAICompatStreamNormalizer("test", thinking_extraction_fields=())
        events = []
        async for message in parser.parse(_chunks(upstream)):
            events.extend(normalizer.normalize(message))

        thinking_deltas = [
            e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, ThinkingDelta)
        ]
        assert len(thinking_deltas) == 0


class TestNormalizerCustomFinishReasonMap:
    """Normalizer with custom finish_reason_map."""

    @pytest.mark.asyncio
    async def test_custom_finish_reason_mapping(self) -> None:
        upstream = (
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"hi"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"eos"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        parser = IncrementalSseParser()
        normalizer = OpenAICompatStreamNormalizer(
            "test",
            finish_reason_map={"eos": "end_turn", "max": "max_tokens"},
        )
        events = []
        async for message in parser.parse(_chunks(upstream)):
            events.extend(normalizer.normalize(message))

        delta_events = [e for e in events if isinstance(e, MessageDeltaEvent)]
        assert len(delta_events) == 1
        assert delta_events[0].stop_reason == "end_turn"


class TestNormalizerCustomTagsStream:
    """Normalizer with custom thinking tags in stream mode."""

    @pytest.mark.asyncio
    async def test_custom_tags_parsed_in_stream(self) -> None:
        upstream = (
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"role":"assistant"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{"content":"<reasoning>plan</reasoning>result"},"finish_reason":null}]}\n\n'
            b'data: {"id":"c","model":"m","choices":[{"index":0,"delta":{},"finish_reason":"stop"}]}\n\n'
            b"data: [DONE]\n\n"
        )
        parser = IncrementalSseParser()
        normalizer = OpenAICompatStreamNormalizer(
            "test",
            thinking_open_tag="<reasoning>",
            thinking_close_tag="</reasoning>",
        )
        events = []
        async for message in parser.parse(_chunks(upstream)):
            events.extend(normalizer.normalize(message))

        thinking_deltas = [
            e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, ThinkingDelta)
        ]
        combined_thinking = "".join(d.delta.thinking for d in thinking_deltas)
        assert combined_thinking == "plan"

        text_deltas = [
            e for e in events if isinstance(e, ContentBlockDeltaEvent) and isinstance(e.delta, TextDelta)
        ]
        combined_text = "".join(d.delta.text for d in text_deltas)
        assert combined_text == "result"


class TestResponseFromOpenaiConfigurable:
    """_response_from_openai with configurable parameters."""

    def test_custom_extraction_fields(self) -> None:
        from llm_proxy.infrastructure.providers.openai_compat import _response_from_openai

        data = {
            "id": "r1",
            "model": "m",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "answer", "thought": "deep"},
                "finish_reason": "stop",
            }],
        }
        resp = _response_from_openai(
            data,
            thinking_extraction_fields=("thought",),
        )
        assert any(isinstance(b, ThinkingBlock) and b.thinking == "deep" for b in resp.content)
        assert any(isinstance(b, TextBlock) and b.text == "answer" for b in resp.content)

    def test_null_tags_no_parsing(self) -> None:
        from llm_proxy.infrastructure.providers.openai_compat import _response_from_openai

        data = {
            "id": "r1",
            "model": "m",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "<think>raw</think>text"},
                "finish_reason": "stop",
            }],
        }
        resp = _response_from_openai(data, thinking_open_tag=None)
        text_blocks = [b for b in resp.content if isinstance(b, TextBlock)]
        assert len(text_blocks) == 1
        assert text_blocks[0].text == "<think>raw</think>text"

    def test_custom_finish_reason_map(self) -> None:
        from llm_proxy.infrastructure.providers.openai_compat import _response_from_openai

        data = {
            "id": "r1",
            "model": "m",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "hi"},
                "finish_reason": "eos",
            }],
        }
        resp = _response_from_openai(data, finish_reason_map={"eos": "end_turn"})
        assert resp.stop_reason == "end_turn"

    def test_custom_tags_in_response(self) -> None:
        from llm_proxy.infrastructure.providers.openai_compat import _response_from_openai

        data = {
            "id": "r1",
            "model": "m",
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": "before<r>thought</r>after"},
                "finish_reason": "stop",
            }],
        }
        resp = _response_from_openai(
            data,
            thinking_open_tag="<r>",
            thinking_close_tag="</r>",
        )
        assert any(isinstance(b, ThinkingBlock) and b.thinking == "thought" for b in resp.content)
        assert any(isinstance(b, TextBlock) and b.text == "before" for b in resp.content)
        assert any(isinstance(b, TextBlock) and b.text == "after" for b in resp.content)
