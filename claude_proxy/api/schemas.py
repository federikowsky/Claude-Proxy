from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from claude_proxy.domain.errors import RequestValidationError
from claude_proxy.domain.models import ChatRequest
from claude_proxy.domain.serialization import (
    content_blocks_from_payload,
    message_from_payload,
    thinking_config_from_payload,
    tool_choice_from_payload,
    tool_definition_from_payload,
)


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    role: Literal["user", "assistant", "system"]
    content: str | list[dict[str, Any]]

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: str | list[dict[str, Any]]) -> str | list[dict[str, Any]]:
        if isinstance(value, str):
            return value
        if not value:
            raise ValueError("content block list must not be empty")
        for item in value:
            if not isinstance(item, dict) or "type" not in item:
                raise ValueError("content blocks must be objects with a type field")
        return value


class _AnthropicRequestBase(BaseModel):
    model_config = ConfigDict(extra="allow")

    model: str
    messages: list[MessageInput] = Field(min_length=1)
    system: str | list[dict[str, Any]] | None = None
    metadata: dict[str, Any] | None = None
    temperature: float | None = None
    top_p: float | None = None
    stop_sequences: list[str] | None = None
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | str | None = None
    thinking: dict[str, Any] | None = None

    def _to_domain(self, *, max_tokens: int, stream: bool) -> ChatRequest:
        tools = tuple(tool_definition_from_payload(item) for item in (self.tools or ()))
        tool_choice = (
            tool_choice_from_payload(self.tool_choice)
            if self.tool_choice is not None
            else None
        )
        thinking = (
            thinking_config_from_payload(self.thinking)
            if self.thinking is not None
            else None
        )
        try:
            return ChatRequest(
                model=self.model,
                messages=tuple(
                    message_from_payload(
                        {
                            "role": message.role,
                            "content": message.content,
                        },
                        strict=True,
                    )
                    for message in self.messages
                ),
                system=content_blocks_from_payload(self.system, strict=True) or None,
                metadata=self.metadata,
                temperature=self.temperature,
                top_p=self.top_p,
                max_tokens=max_tokens,
                stop_sequences=tuple(self.stop_sequences or ()),
                tools=tools,
                tool_choice=tool_choice,
                thinking=thinking,
                stream=stream,
                extensions=dict(self.model_extra or {}),
            )
        except RequestValidationError:
            raise
        except Exception as exc:
            raise RequestValidationError(str(exc)) from exc


class AnthropicMessagesRequest(_AnthropicRequestBase):
    max_tokens: int = Field(gt=0)
    stream: bool = False

    def to_domain(self) -> ChatRequest:
        return self._to_domain(max_tokens=self.max_tokens, stream=self.stream)


class AnthropicCountTokensRequest(_AnthropicRequestBase):
    def to_domain(self) -> ChatRequest:
        return self._to_domain(max_tokens=1, stream=False)
