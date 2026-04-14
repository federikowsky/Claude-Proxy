"""Tests for the OpenAI Chat Completions ingress schema."""

from __future__ import annotations

import pytest

from llm_proxy.api.schemas_openai import (
    OpenAIChatCompletionsRequest,
    OpenAIContentPart,
    OpenAIFunctionDef,
    OpenAIMessage,
    OpenAIToolCall,
    OpenAIToolCallFunction,
    OpenAIToolChoiceFunction,
    OpenAIToolChoiceObject,
    OpenAIToolDef,
)
from llm_proxy.domain.enums import Role
from llm_proxy.domain.models import TextBlock, ToolResultBlock, ToolUseBlock


class TestOpenAIToDomain:
    """Test OpenAIChatCompletionsRequest.to_domain() translation."""

    def _minimal_request(self, **overrides) -> OpenAIChatCompletionsRequest:
        defaults = {
            "model": "gpt-4.1",
            "messages": [OpenAIMessage(role="user", content="Hello")],
        }
        defaults.update(overrides)
        return OpenAIChatCompletionsRequest(**defaults)

    def test_minimal_request(self):
        req = self._minimal_request()
        domain = req.to_domain()
        assert domain.model == "gpt-4.1"
        assert len(domain.messages) == 1
        assert domain.messages[0].role == Role.USER
        block = domain.messages[0].content[0]
        assert isinstance(block, TextBlock)
        assert block.text == "Hello"
        assert domain.stream is False
        assert domain.max_tokens == 4096  # default

    def test_system_message_extracted(self):
        req = self._minimal_request(
            messages=[
                OpenAIMessage(role="system", content="You are helpful."),
                OpenAIMessage(role="user", content="Hi"),
            ]
        )
        domain = req.to_domain()
        assert domain.system is not None
        assert len(domain.system) == 1
        assert isinstance(domain.system[0], TextBlock)
        assert domain.system[0].text == "You are helpful."
        assert len(domain.messages) == 1
        assert domain.messages[0].role == Role.USER

    def test_multiple_system_messages_merged(self):
        req = self._minimal_request(
            messages=[
                OpenAIMessage(role="system", content="Part 1."),
                OpenAIMessage(role="system", content="Part 2."),
                OpenAIMessage(role="user", content="Hi"),
            ]
        )
        domain = req.to_domain()
        assert domain.system is not None
        assert len(domain.system) == 2
        assert domain.system[0].text == "Part 1."
        assert domain.system[1].text == "Part 2."

    def test_content_parts_array(self):
        req = self._minimal_request(
            messages=[
                OpenAIMessage(
                    role="user",
                    content=[
                        OpenAIContentPart(type="text", text="Hello"),
                        OpenAIContentPart(type="text", text="World"),
                    ],
                ),
            ]
        )
        domain = req.to_domain()
        block = domain.messages[0].content[0]
        assert isinstance(block, TextBlock)
        assert block.text == "Hello\nWorld"

    def test_assistant_message_with_tool_calls(self):
        req = self._minimal_request(
            messages=[
                OpenAIMessage(role="user", content="What's the weather?"),
                OpenAIMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        OpenAIToolCall(
                            id="call_123",
                            function=OpenAIToolCallFunction(
                                name="get_weather",
                                arguments='{"city": "Rome"}',
                            ),
                        )
                    ],
                ),
                OpenAIMessage(role="tool", content="22°C sunny", tool_call_id="call_123"),
                OpenAIMessage(role="user", content="Thanks"),
            ]
        )
        domain = req.to_domain()
        # assistant message has a ToolUseBlock
        assert len(domain.messages) == 4
        assistant_blocks = domain.messages[1].content
        assert len(assistant_blocks) == 1
        assert isinstance(assistant_blocks[0], ToolUseBlock)
        assert assistant_blocks[0].name == "get_weather"
        assert assistant_blocks[0].input == {"city": "Rome"}
        # tool result
        tool_msg = domain.messages[2]
        assert tool_msg.role == Role.USER
        assert isinstance(tool_msg.content[0], ToolResultBlock)
        assert tool_msg.content[0].tool_use_id == "call_123"
        assert tool_msg.content[0].content == "22°C sunny"

    def test_streaming_flag(self):
        req = self._minimal_request(stream=True)
        domain = req.to_domain()
        assert domain.stream is True

    def test_temperature_and_top_p(self):
        req = self._minimal_request(temperature=0.7, top_p=0.9)
        domain = req.to_domain()
        assert domain.temperature == 0.7
        assert domain.top_p == 0.9

    def test_max_completion_tokens_preferred(self):
        req = self._minimal_request(max_tokens=100, max_completion_tokens=200)
        domain = req.to_domain()
        assert domain.max_tokens == 200

    def test_stop_string(self):
        req = self._minimal_request(stop="END")
        domain = req.to_domain()
        assert domain.stop_sequences == ("END",)

    def test_stop_list(self):
        req = self._minimal_request(stop=["END", "STOP"])
        domain = req.to_domain()
        assert domain.stop_sequences == ("END", "STOP")

    def test_tools_conversion(self):
        req = self._minimal_request(
            tools=[
                OpenAIToolDef(
                    function=OpenAIFunctionDef(
                        name="get_weather",
                        description="Get weather for a city",
                        parameters={"type": "object", "properties": {"city": {"type": "string"}}},
                    )
                )
            ]
        )
        domain = req.to_domain()
        assert len(domain.tools) == 1
        assert domain.tools[0].name == "get_weather"
        assert domain.tools[0].description == "Get weather for a city"

    def test_tool_choice_auto(self):
        req = self._minimal_request(tool_choice="auto")
        domain = req.to_domain()
        assert domain.tool_choice is not None
        assert domain.tool_choice.type == "auto"

    def test_tool_choice_required(self):
        req = self._minimal_request(tool_choice="required")
        domain = req.to_domain()
        assert domain.tool_choice is not None
        assert domain.tool_choice.type == "any"

    def test_tool_choice_specific_function(self):
        req = self._minimal_request(
            tool_choice=OpenAIToolChoiceObject(
                function=OpenAIToolChoiceFunction(name="get_weather"),
            )
        )
        domain = req.to_domain()
        assert domain.tool_choice is not None
        assert domain.tool_choice.type == "tool"
        assert domain.tool_choice.name == "get_weather"

    def test_none_content_assistant_with_tool_calls(self):
        """Assistant message with content=None but tool_calls should produce only ToolUseBlocks."""
        req = self._minimal_request(
            messages=[
                OpenAIMessage(role="user", content="Do something"),
                OpenAIMessage(
                    role="assistant",
                    content=None,
                    tool_calls=[
                        OpenAIToolCall(
                            id="call_abc",
                            function=OpenAIToolCallFunction(name="fn", arguments="{}"),
                        )
                    ],
                ),
            ]
        )
        domain = req.to_domain()
        blocks = domain.messages[1].content
        assert len(blocks) == 1
        assert isinstance(blocks[0], ToolUseBlock)
