"""Pydantic request schemas for the OpenAI Chat Completions ingress.

Translates an OpenAI-format request into the domain ChatRequest so that
MessageService can process it with the same pipeline as Anthropic ingress.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from llm_proxy.domain.enums import Role
from llm_proxy.domain.errors import RequestValidationError
from llm_proxy.domain.models import (
    ChatRequest,
    Message,
    TextBlock,
    ToolChoice,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
)


# ---------------------------------------------------------------------------
# Sub-models
# ---------------------------------------------------------------------------


class OpenAIFunctionDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    name: str
    description: str | None = None
    parameters: dict[str, Any] | None = None


class OpenAIToolDef(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: Literal["function"] = "function"
    function: OpenAIFunctionDef


class OpenAIToolChoiceFunction(BaseModel):
    name: str


class OpenAIToolChoiceObject(BaseModel):
    type: Literal["function"] = "function"
    function: OpenAIToolChoiceFunction


class OpenAIToolCallFunction(BaseModel):
    name: str
    arguments: str


class OpenAIToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: OpenAIToolCallFunction


class OpenAIContentPart(BaseModel):
    model_config = ConfigDict(extra="allow")
    type: str
    text: str | None = None


class OpenAIMessage(BaseModel):
    model_config = ConfigDict(extra="allow")
    role: Literal["system", "user", "assistant", "tool"]
    content: str | list[OpenAIContentPart] | None = None
    name: str | None = None
    tool_calls: list[OpenAIToolCall] | None = None
    tool_call_id: str | None = None


# ---------------------------------------------------------------------------
# Main request
# ---------------------------------------------------------------------------


class OpenAIChatCompletionsRequest(BaseModel):
    """OpenAI Chat Completions request schema.

    Reference: https://platform.openai.com/docs/api-reference/chat/create
    """

    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[OpenAIMessage] = Field(min_length=1)
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    max_completion_tokens: int | None = None
    stop: str | list[str] | None = None
    stream: bool = False
    tools: list[OpenAIToolDef] | None = None
    tool_choice: str | OpenAIToolChoiceObject | None = None

    @field_validator("messages")
    @classmethod
    def validate_messages(cls, value: list[OpenAIMessage]) -> list[OpenAIMessage]:
        if not value:
            raise ValueError("messages must not be empty")
        return value

    def to_domain(self) -> ChatRequest:
        """Convert to domain ChatRequest (Anthropic-canonical format)."""
        try:
            system, messages = self._split_system_and_messages()
            tools = self._convert_tools()
            tool_choice = self._convert_tool_choice()
            max_tokens = self.max_completion_tokens or self.max_tokens or 4096

            return ChatRequest(
                model=self.model,
                messages=tuple(messages),
                system=system,
                metadata=None,
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=max_tokens,
                stop_sequences=self._normalize_stop(),
                tools=tools,
                tool_choice=tool_choice,
                thinking=None,
                stream=self.stream,
                extensions=dict(self.model_extra or {}),
            )
        except RequestValidationError:
            raise
        except Exception as exc:
            raise RequestValidationError(str(exc)) from exc

    def _split_system_and_messages(
        self,
    ) -> tuple[tuple[TextBlock, ...] | None, list[Message]]:
        system_blocks: list[TextBlock] = []
        domain_messages: list[Message] = []

        for msg in self.messages:
            if msg.role == "system":
                text = self._extract_text(msg)
                if text:
                    system_blocks.append(TextBlock(text=text))
                continue

            if msg.role == "tool":
                # OpenAI tool result → Anthropic tool_result block
                domain_messages.append(
                    Message(
                        role=Role.USER,
                        content=(
                            ToolResultBlock(
                                tool_use_id=msg.tool_call_id or "",
                                content=self._extract_text(msg),
                            ),
                        ),
                    )
                )
                continue

            role = Role.USER if msg.role == "user" else Role.ASSISTANT
            blocks = self._message_to_content_blocks(msg)
            if blocks:
                domain_messages.append(Message(role=role, content=tuple(blocks)))

        system = tuple(system_blocks) if system_blocks else None
        return system, domain_messages

    def _message_to_content_blocks(self, msg: OpenAIMessage) -> list[TextBlock | ToolUseBlock]:
        blocks: list[TextBlock | ToolUseBlock] = []

        # Text content
        text = self._extract_text(msg)
        if text:
            blocks.append(TextBlock(text=text))

        # Tool calls (assistant messages)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                import json as _json
                try:
                    input_data = _json.loads(tc.function.arguments)
                except (ValueError, TypeError):
                    input_data = {"raw": tc.function.arguments}
                blocks.append(
                    ToolUseBlock(
                        id=tc.id,
                        name=tc.function.name,
                        input=input_data,
                    )
                )

        return blocks

    @staticmethod
    def _extract_text(msg: OpenAIMessage) -> str | None:
        if msg.content is None:
            return None
        if isinstance(msg.content, str):
            return msg.content
        parts = [p.text for p in msg.content if p.type == "text" and p.text]
        return "\n".join(parts) if parts else None

    def _normalize_stop(self) -> tuple[str, ...]:
        if self.stop is None:
            return ()
        if isinstance(self.stop, str):
            return (self.stop,)
        return tuple(self.stop)

    def _convert_tools(self) -> tuple[ToolDefinition, ...]:
        if not self.tools:
            return ()
        return tuple(
            ToolDefinition(
                name=t.function.name,
                description=t.function.description,
                input_schema=t.function.parameters or {"type": "object", "properties": {}},
            )
            for t in self.tools
        )

    def _convert_tool_choice(self) -> ToolChoice | None:
        if self.tool_choice is None:
            return None
        if isinstance(self.tool_choice, str):
            mapping = {"auto": "auto", "none": "none", "required": "any"}
            tc_type = mapping.get(self.tool_choice, self.tool_choice)
            return ToolChoice(type=tc_type)
        # Object form: {"type": "function", "function": {"name": "..."}}
        return ToolChoice(type="tool", name=self.tool_choice.function.name)
