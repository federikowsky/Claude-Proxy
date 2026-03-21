from __future__ import annotations

from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, field_validator

from claude_proxy.domain.enums import Role
from claude_proxy.domain.models import ChatMessage, ChatRequest


class TextBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["text"]
    text: str


TextContent: TypeAlias = str | list[TextBlock]


class MessageInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: Literal["user", "assistant", "system"]
    content: TextContent

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: TextContent) -> TextContent:
        text = collapse_text_content(value)
        if not text:
            raise ValueError("text content must not be empty")
        return value


class AnthropicMessagesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model: str
    messages: list[MessageInput] = Field(min_length=1)
    system: TextContent | None = None
    max_tokens: int = Field(gt=0)
    temperature: float | None = None
    stream: Literal[True]
    metadata: dict[str, str] | None = None

    def to_domain(self) -> ChatRequest:
        return ChatRequest(
            model=self.model,
            messages=tuple(
                ChatMessage(role=Role(message.role), text=collapse_text_content(message.content) or "")
                for message in self.messages
            ),
            system=collapse_text_content(self.system),
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            stream=self.stream,
            metadata=self.metadata,
        )


def collapse_text_content(content: TextContent | None) -> str | None:
    if content is None:
        return None
    if isinstance(content, str):
        return content
    return "".join(block.text for block in content)

