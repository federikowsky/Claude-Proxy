from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypeAlias

from llm_proxy.domain.enums import ActionPolicy, Role, ThinkingPassthroughMode, ToolCategory


JsonMap: TypeAlias = Mapping[str, Any]


@dataclass(slots=True, frozen=True)
class TextBlock:
    text: str
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="text")


@dataclass(slots=True, frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: Any
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="tool_use")


@dataclass(slots=True, frozen=True)
class ThinkingBlock:
    thinking: str
    signature: str | None = None
    source_type: str = "thinking"
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="thinking")


@dataclass(slots=True, frozen=True)
class UnknownBlock:
    unknown_type: str
    payload: JsonMap
    type: str = field(init=False, default="unknown")


@dataclass(slots=True, frozen=True)
class ToolResultBlock:
    tool_use_id: str
    content: str | tuple[ContentBlock, ...] | None = None
    is_error: bool = False
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="tool_result")


ContentBlock = TextBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock | UnknownBlock


@dataclass(slots=True, frozen=True)
class Message:
    role: Role
    content: tuple[ContentBlock, ...]


ChatMessage = Message


@dataclass(slots=True, frozen=True)
class ToolDefinition:
    name: str
    description: str | None
    input_schema: JsonMap
    extras: JsonMap = field(default_factory=dict)
    # Set by ToolClassifier after classification; defaults to ORDINARY so that
    # existing code that creates ToolDefinition without a classifier still works.
    category: ToolCategory = ToolCategory.ORDINARY


@dataclass(slots=True, frozen=True)
class ToolChoice:
    type: str
    name: str | None = None
    extras: JsonMap = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ThinkingConfig:
    type: str = "enabled"
    budget_tokens: int | None = None
    extras: JsonMap = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ChatRequest:
    model: str
    messages: tuple[Message, ...]
    system: tuple[ContentBlock, ...] | None
    metadata: JsonMap | None
    temperature: float | None
    top_p: float | None
    max_tokens: int
    stop_sequences: tuple[str, ...]
    tools: tuple[ToolDefinition, ...]
    tool_choice: ToolChoice | None
    thinking: ThinkingConfig | None
    stream: bool
    extensions: JsonMap = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProviderRequestContext:
    headers: tuple[tuple[str, str], ...] = ()
    query_params: tuple[tuple[str, str], ...] = ()


@dataclass(slots=True, frozen=True)
class ModelInfo:
    name: str
    provider: str
    enabled: bool
    supports_stream: bool
    supports_nonstream: bool
    supports_tools: bool
    supports_thinking: bool
    thinking_passthrough_mode: ThinkingPassthroughMode = ThinkingPassthroughMode.FULL
    thinking_open_tag: str | None = "<think>"
    thinking_close_tag: str | None = "</think>"
    thinking_extraction_fields: tuple[str, ...] = ("reasoning_content", "reasoning")
    unsupported_request_fields: tuple[str, ...] = ()
    # ---- Capability / policy fields introduced by the runtime bridge ----
    # Policy for normalising tool input_schema before provider boundary.
    schema_normalization_policy: ActionPolicy = ActionPolicy.ALLOW
    # Policy for handling detected state/control transition actions.
    control_action_policy: ActionPolicy = ActionPolicy.WARN
    # Policy for handling detected orchestration actions.
    orchestration_action_policy: ActionPolicy = ActionPolicy.WARN
    # Policy for handling detected generic-tool emulation of runtime semantics.
    generic_tool_emulation_policy: ActionPolicy = ActionPolicy.WARN


@dataclass(slots=True, frozen=True)
class Usage:
    input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_tokens: int | None = None
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None
    extra: JsonMap = field(default_factory=dict)

    def merged(self, other: Usage | None) -> Usage:
        if other is None:
            return self
        merged_extra = {**dict(self.extra), **dict(other.extra)}
        return Usage(
            input_tokens=other.input_tokens if other.input_tokens is not None else self.input_tokens,
            output_tokens=other.output_tokens if other.output_tokens is not None else self.output_tokens,
            reasoning_tokens=other.reasoning_tokens
            if other.reasoning_tokens is not None
            else self.reasoning_tokens,
            cache_creation_input_tokens=other.cache_creation_input_tokens
            if other.cache_creation_input_tokens is not None
            else self.cache_creation_input_tokens,
            cache_read_input_tokens=other.cache_read_input_tokens
            if other.cache_read_input_tokens is not None
            else self.cache_read_input_tokens,
            extra=merged_extra,
        )

    def to_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        if self.input_tokens is not None:
            payload["input_tokens"] = self.input_tokens
        if self.output_tokens is not None:
            payload["output_tokens"] = self.output_tokens
        if self.reasoning_tokens is not None:
            payload["reasoning_tokens"] = self.reasoning_tokens
        if self.cache_creation_input_tokens is not None:
            payload["cache_creation_input_tokens"] = self.cache_creation_input_tokens
        if self.cache_read_input_tokens is not None:
            payload["cache_read_input_tokens"] = self.cache_read_input_tokens
        payload.update(dict(self.extra))
        return payload


@dataclass(slots=True, frozen=True)
class ChatResponse:
    id: str
    role: Role
    model: str
    content: tuple[ContentBlock, ...]
    stop_reason: str | None
    stop_sequence: str | None
    usage: Usage
    metadata: JsonMap | None = None
    extras: JsonMap = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class TextDelta:
    text: str
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="text_delta")


@dataclass(slots=True, frozen=True)
class InputJsonDelta:
    partial_json: str
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="input_json_delta")


@dataclass(slots=True, frozen=True)
class ThinkingDelta:
    thinking: str
    source_type: str = "thinking"
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="thinking_delta")


@dataclass(slots=True, frozen=True)
class SignatureDelta:
    signature: str
    source_type: str = "thinking"
    extras: JsonMap = field(default_factory=dict)
    type: str = field(init=False, default="signature_delta")


@dataclass(slots=True, frozen=True)
class UnknownDelta:
    delta_type: str
    payload: JsonMap
    type: str = field(init=False, default="unknown_delta")


ContentDelta: TypeAlias = TextDelta | InputJsonDelta | ThinkingDelta | SignatureDelta | UnknownDelta


@dataclass(slots=True, frozen=True)
class MessageStartEvent:
    message: ChatResponse


@dataclass(slots=True, frozen=True)
class ContentBlockStartEvent:
    index: int
    block: ContentBlock


@dataclass(slots=True, frozen=True)
class ContentBlockDeltaEvent:
    index: int
    delta: ContentDelta


@dataclass(slots=True, frozen=True)
class ContentBlockStopEvent:
    index: int


@dataclass(slots=True, frozen=True)
class MessageDeltaEvent:
    stop_reason: str | None = None
    stop_sequence: str | None = None
    usage: Usage | None = None
    extras: JsonMap = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class MessageStopEvent:
    pass


@dataclass(slots=True, frozen=True)
class PingEvent:
    payload: JsonMap = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ProviderWarningEvent:
    message: str
    payload: JsonMap = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ErrorEvent:
    message: str
    error_type: str = "error"


CanonicalEvent: TypeAlias = (
    MessageStartEvent
    | ContentBlockStartEvent
    | ContentBlockDeltaEvent
    | ContentBlockStopEvent
    | MessageDeltaEvent
    | MessageStopEvent
    | PingEvent
    | ProviderWarningEvent
    | ErrorEvent
)


DomainEvent = CanonicalEvent
