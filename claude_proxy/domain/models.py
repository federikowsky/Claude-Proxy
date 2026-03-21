from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypeAlias

from claude_proxy.domain.enums import ReasoningMode, Role


@dataclass(slots=True, frozen=True)
class ChatMessage:
    role: Role
    text: str


@dataclass(slots=True, frozen=True)
class ChatRequest:
    model: str
    messages: tuple[ChatMessage, ...]
    system: str | None
    max_tokens: int
    temperature: float | None
    stream: bool
    metadata: Mapping[str, str] | None = None


@dataclass(slots=True, frozen=True)
class ModelInfo:
    name: str
    provider: str
    enabled: bool
    supports_streaming: bool
    supports_text: bool
    supports_tools: bool
    supports_multimodal: bool
    reasoning_mode: ReasoningMode


@dataclass(slots=True, frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None

    def to_payload(self) -> dict[str, int]:
        payload: dict[str, int] = {}
        if self.input_tokens is not None:
            payload["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            payload["output_tokens"] = self.output_tokens
        return payload


@dataclass(slots=True, frozen=True)
class RawTextDelta:
    text: str


@dataclass(slots=True, frozen=True)
class RawReasoningDelta:
    text: str


@dataclass(slots=True, frozen=True)
class RawUsage:
    usage: Usage


@dataclass(slots=True, frozen=True)
class RawStop:
    stop_reason: str | None = None


@dataclass(slots=True, frozen=True)
class RawUnknown:
    event_type: str


@dataclass(slots=True, frozen=True)
class RawError:
    message: str
    error_type: str = "provider_error"


ProviderEvent: TypeAlias = (
    RawTextDelta
    | RawReasoningDelta
    | RawUsage
    | RawStop
    | RawUnknown
    | RawError
)


@dataclass(slots=True, frozen=True)
class MessageStartEvent:
    model: str


@dataclass(slots=True, frozen=True)
class TextStartEvent:
    index: int = 0


@dataclass(slots=True, frozen=True)
class TextDeltaEvent:
    text: str


@dataclass(slots=True, frozen=True)
class TextStopEvent:
    index: int = 0


@dataclass(slots=True, frozen=True)
class UsageEvent:
    usage: Usage


@dataclass(slots=True, frozen=True)
class MessageStopEvent:
    stop_reason: str | None = None


@dataclass(slots=True, frozen=True)
class ProviderWarningEvent:
    message: str


@dataclass(slots=True, frozen=True)
class ErrorEvent:
    message: str
    error_type: str = "error"


DomainEvent: TypeAlias = (
    MessageStartEvent
    | TextStartEvent
    | TextDeltaEvent
    | TextStopEvent
    | UsageEvent
    | MessageStopEvent
    | ProviderWarningEvent
    | ErrorEvent
)

