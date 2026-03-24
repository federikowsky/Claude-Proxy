from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Any

from claude_proxy.domain.enums import Role
from claude_proxy.domain.errors import RequestValidationError
from claude_proxy.domain.models import (
    ChatResponse,
    ContentBlock,
    ContentDelta,
    InputJsonDelta,
    Message,
    SignatureDelta,
    TextBlock,
    TextDelta,
    ThinkingBlock,
    ThinkingConfig,
    ThinkingDelta,
    ToolChoice,
    ToolDefinition,
    ToolResultBlock,
    ToolUseBlock,
    UnknownBlock,
    UnknownDelta,
    Usage,
)

_logger = logging.getLogger("claude_proxy.serialization")

# ---------------------------------------------------------------------------
# Fallback object schema used whenever a tool definition has a missing or
# invalid input_schema.  A single canonical constant avoids repeated dict
# construction and makes intent explicit.
# ---------------------------------------------------------------------------
_FALLBACK_OBJECT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


def normalize_tool_schema(
    schema: Any,
    *,
    tool_name: str = "<unknown>",
) -> dict[str, Any]:
    """Return a deterministically normalised copy of *schema* suitable for provider emission.

    Normalisation rules (applied in order):

    1. None / missing              → fallback object schema  (``schema_missing``)
    2. Non-mapping                 → fallback object schema  (``schema_invalid_type``)
    3. Empty mapping               → fallback object schema  (``schema_empty``)
    4. Mapping with no ``type`` key:
       a. Has ``properties`` or ``required``
          → inject ``type: object``  (``schema_type_injected``)
       b. Has neither (arbitrary schema with no type hint)
          → inject ``type: object`` + ``properties: {}``  (``schema_type_properties_injected``)
    5. ``type == "object"`` (or just injected):
       - no ``properties`` key → inject empty ``properties: {}``  (``schema_properties_injected``)
       - ``required`` non-list  → strip  (``schema_required_sanitized``)
       - ``required`` with non-string items → filter  (``schema_required_filtered``)
    6. Preserve extra keys in all cases.

    Always returns a fresh plain ``dict`` — never the original Mapping reference.
    """
    # Rules 1-3: missing, non-mapping, or empty → fallback
    if schema is None:
        _logger.debug(
            "tool_schema_repair tool=%s repair=schema_missing",
            tool_name,
            extra={"extra_fields": {"tool": tool_name, "repair": "schema_missing"}},
        )
        return dict(_FALLBACK_OBJECT_SCHEMA)

    if not isinstance(schema, Mapping):
        _logger.debug(
            "tool_schema_repair tool=%s repair=schema_invalid_type actual_type=%s",
            tool_name,
            type(schema).__name__,
            extra={"extra_fields": {"tool": tool_name, "repair": "schema_invalid_type"}},
        )
        return dict(_FALLBACK_OBJECT_SCHEMA)

    if not schema:
        _logger.debug(
            "tool_schema_repair tool=%s repair=schema_empty",
            tool_name,
            extra={"extra_fields": {"tool": tool_name, "repair": "schema_empty"}},
        )
        return dict(_FALLBACK_OBJECT_SCHEMA)

    # Work on a mutable shallow copy so we never mutate the original.
    result: dict[str, Any] = dict(schema)

    # Rule 4: no explicit type key
    if "type" not in result:
        if "properties" in result or "required" in result:
            # 4a: object-like hints
            result["type"] = "object"
            _logger.debug(
                "tool_schema_repair tool=%s repair=schema_type_injected",
                tool_name,
                extra={"extra_fields": {"tool": tool_name, "repair": "schema_type_injected"}},
            )
        else:
            # 4b: no hints at all → treat as empty object schema
            result["type"] = "object"
            result.setdefault("properties", {})
            _logger.debug(
                "tool_schema_repair tool=%s repair=schema_type_properties_injected",
                tool_name,
                extra={"extra_fields": {"tool": tool_name, "repair": "schema_type_properties_injected"}},
            )

    schema_type = result.get("type")

    # Rule 5: object-type specific normalisation
    if schema_type == "object":
        if "properties" not in result:
            result["properties"] = {}
            _logger.debug(
                "tool_schema_repair tool=%s repair=schema_properties_injected",
                tool_name,
                extra={"extra_fields": {"tool": tool_name, "repair": "schema_properties_injected"}},
            )

        if "required" in result:
            req = result["required"]
            if not isinstance(req, list):
                del result["required"]
                _logger.debug(
                    "tool_schema_repair tool=%s repair=schema_required_sanitized",
                    tool_name,
                    extra={"extra_fields": {"tool": tool_name, "repair": "schema_required_sanitized"}},
                )
            else:
                filtered = [item for item in req if isinstance(item, str)]
                if len(filtered) != len(req):
                    result["required"] = filtered
                    _logger.debug(
                        "tool_schema_repair tool=%s repair=schema_required_filtered removed=%d",
                        tool_name,
                        len(req) - len(filtered),
                        extra={"extra_fields": {"tool": tool_name, "repair": "schema_required_filtered"}},
                    )

    return result


# ---------------------------------------------------------------------------
# Existing serialisation helpers — unchanged
# ---------------------------------------------------------------------------


def message_from_payload(payload: Mapping[str, Any], *, strict: bool) -> Message:
    role_value = payload.get("role")
    if not isinstance(role_value, str):
        raise RequestValidationError("message role is required")
    try:
        role = Role(role_value)
    except ValueError as exc:
        raise RequestValidationError(f"unsupported message role '{role_value}'") from exc
    return Message(
        role=role,
        content=content_blocks_from_payload(payload.get("content"), strict=strict),
    )


def content_blocks_from_payload(value: Any, *, strict: bool) -> tuple[ContentBlock, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (TextBlock(text=value),)
    if not isinstance(value, Sequence) or isinstance(value, (bytes, bytearray, str)):
        raise RequestValidationError("content must be a string or a list of content blocks")
    blocks: list[ContentBlock] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise RequestValidationError("content block must be an object")
        blocks.append(content_block_from_payload(item, strict=strict))
    return tuple(blocks)


def content_block_from_payload(payload: Mapping[str, Any], *, strict: bool) -> ContentBlock:
    block_type = payload.get("type")
    if not isinstance(block_type, str) or not block_type:
        if strict:
            raise RequestValidationError("content block type is required")
        return UnknownBlock(unknown_type="unknown", payload=dict(payload))

    extras = _extras(payload, {"type"})
    if block_type == "text":
        text = payload.get("text", "")
        if not isinstance(text, str):
            raise RequestValidationError("text block must contain a string text field")
        return TextBlock(text=text, extras=_extras(payload, {"type", "text"}))

    if block_type == "tool_use":
        tool_id = payload.get("id")
        name = payload.get("name")
        if strict and (not isinstance(tool_id, str) or not isinstance(name, str)):
            raise RequestValidationError("tool_use block requires id and name")
        return ToolUseBlock(
            id=tool_id if isinstance(tool_id, str) else "",
            name=name if isinstance(name, str) else "",
            input=payload.get("input", {}),
            extras=_extras(payload, {"type", "id", "name", "input"}),
        )

    if block_type == "tool_result":
        tool_use_id = payload.get("tool_use_id")
        if strict and not isinstance(tool_use_id, str):
            raise RequestValidationError("tool_result block requires tool_use_id")
        content = payload.get("content")
        normalized_content: str | tuple[ContentBlock, ...] | None
        if isinstance(content, str) or content is None:
            normalized_content = content
        else:
            normalized_content = content_blocks_from_payload(content, strict=strict)
        return ToolResultBlock(
            tool_use_id=tool_use_id if isinstance(tool_use_id, str) else "",
            content=normalized_content,
            is_error=bool(payload.get("is_error", False)),
            extras=_extras(payload, {"type", "tool_use_id", "content", "is_error"}),
        )

    if block_type in {"thinking", "reasoning", "redacted_thinking"}:
        thinking = payload.get("thinking") or payload.get("text") or payload.get("reasoning") or ""
        signature = payload.get("signature")
        if not isinstance(thinking, str):
            thinking = ""
        if block_type == "redacted_thinking" and not thinking:
            return UnknownBlock(unknown_type=block_type, payload=dict(payload))
        return ThinkingBlock(
            thinking=thinking,
            signature=signature if isinstance(signature, str) else None,
            source_type=block_type,
            extras=_extras(payload, {"type", "thinking", "text", "reasoning", "signature"}),
        )

    return UnknownBlock(unknown_type=block_type, payload=dict(payload))


def content_block_to_payload(block: ContentBlock) -> dict[str, Any]:
    if isinstance(block, TextBlock):
        return {"type": "text", "text": block.text, **dict(block.extras)}
    if isinstance(block, ToolUseBlock):
        return {
            "type": "tool_use",
            "id": block.id,
            "name": block.name,
            "input": block.input,
            **dict(block.extras),
        }
    if isinstance(block, ToolResultBlock):
        payload: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": block.tool_use_id,
            **dict(block.extras),
        }
        if block.content is not None:
            payload["content"] = (
                block.content
                if isinstance(block.content, str)
                else [content_block_to_payload(item) for item in block.content]
            )
        if block.is_error:
            payload["is_error"] = True
        return payload
    if isinstance(block, ThinkingBlock):
        payload = {"type": "thinking", "thinking": block.thinking, **dict(block.extras)}
        if block.signature is not None:
            payload["signature"] = block.signature
        return payload
    if isinstance(block, UnknownBlock):
        return dict(block.payload)
    raise TypeError(f"unsupported content block: {type(block)!r}")


def tool_definition_from_payload(payload: Mapping[str, Any]) -> ToolDefinition:
    name = payload.get("name")
    input_schema = payload.get("input_schema")
    if not isinstance(name, str):
        raise RequestValidationError("tool definition requires name")
    if not isinstance(input_schema, Mapping):
        raise RequestValidationError("tool definition requires input_schema")
    description = payload.get("description")
    return ToolDefinition(
        name=name,
        description=description if isinstance(description, str) else None,
        input_schema=dict(input_schema),
        extras=_extras(payload, {"name", "description", "input_schema"}),
    )


def tool_definition_to_payload(tool: ToolDefinition) -> dict[str, Any]:
    payload = {
        "name": tool.name,
        "input_schema": dict(tool.input_schema),
        **dict(tool.extras),
    }
    if tool.description is not None:
        payload["description"] = tool.description
    return payload


def tool_choice_from_payload(value: Mapping[str, Any] | str) -> ToolChoice:
    if isinstance(value, str):
        return ToolChoice(type=value)
    choice_type = value.get("type")
    if not isinstance(choice_type, str):
        raise RequestValidationError("tool_choice requires a type")
    name = value.get("name")
    return ToolChoice(
        type=choice_type,
        name=name if isinstance(name, str) else None,
        extras=_extras(value, {"type", "name"}),
    )


def tool_choice_to_payload(choice: ToolChoice) -> dict[str, Any]:
    payload = {"type": choice.type, **dict(choice.extras)}
    if choice.name is not None:
        payload["name"] = choice.name
    return payload


def thinking_config_from_payload(payload: Mapping[str, Any]) -> ThinkingConfig:
    config_type = payload.get("type", "enabled")
    if not isinstance(config_type, str):
        raise RequestValidationError("thinking.type must be a string")
    budget_tokens = payload.get("budget_tokens")
    return ThinkingConfig(
        type=config_type,
        budget_tokens=budget_tokens if isinstance(budget_tokens, int) else None,
        extras=_extras(payload, {"type", "budget_tokens"}),
    )


def thinking_config_to_payload(config: ThinkingConfig) -> dict[str, Any]:
    payload = {"type": config.type, **dict(config.extras)}
    if config.budget_tokens is not None:
        payload["budget_tokens"] = config.budget_tokens
    return payload


def usage_from_payload(payload: Any) -> Usage:
    if not isinstance(payload, Mapping):
        return Usage()
    known = {
        "input_tokens",
        "output_tokens",
        "reasoning_tokens",
        "cache_creation_input_tokens",
        "cache_read_input_tokens",
    }
    return Usage(
        input_tokens=_int_or_none(payload.get("input_tokens")),
        output_tokens=_int_or_none(payload.get("output_tokens")),
        reasoning_tokens=_int_or_none(payload.get("reasoning_tokens")),
        cache_creation_input_tokens=_int_or_none(payload.get("cache_creation_input_tokens")),
        cache_read_input_tokens=_int_or_none(payload.get("cache_read_input_tokens")),
        extra={key: value for key, value in payload.items() if key not in known},
    )


def response_from_payload(payload: Mapping[str, Any]) -> ChatResponse:
    role_value = payload.get("role", "assistant")
    try:
        role = Role(role_value)
    except ValueError:
        role = Role.ASSISTANT
    content = content_blocks_from_payload(payload.get("content"), strict=False)
    metadata = payload.get("metadata")
    return ChatResponse(
        id=str(payload.get("id") or ""),
        role=role,
        model=str(payload.get("model") or ""),
        content=content,
        stop_reason=payload.get("stop_reason") if isinstance(payload.get("stop_reason"), str) else None,
        stop_sequence=payload.get("stop_sequence")
        if isinstance(payload.get("stop_sequence"), str)
        else None,
        usage=usage_from_payload(payload.get("usage")),
        metadata=dict(metadata) if isinstance(metadata, Mapping) else None,
        extras=_extras(
            payload,
            {"id", "type", "role", "model", "content", "stop_reason", "stop_sequence", "usage", "metadata"},
        ),
    )


def response_to_payload(response: ChatResponse) -> dict[str, Any]:
    payload = {
        "id": response.id,
        "type": "message",
        "role": response.role.value,
        "model": response.model,
        "content": [content_block_to_payload(block) for block in response.content],
        "stop_reason": response.stop_reason,
        "stop_sequence": response.stop_sequence,
        "usage": response.usage.to_payload(),
        **dict(response.extras),
    }
    if response.metadata is not None:
        payload["metadata"] = dict(response.metadata)
    return payload


def delta_from_payload(payload: Mapping[str, Any], *, block: ContentBlock | None) -> ContentDelta | None:
    delta_type = payload.get("type")
    if not isinstance(delta_type, str) or not delta_type:
        return UnknownDelta(delta_type="unknown", payload=dict(payload))

    if delta_type == "text_delta":
        if isinstance(block, ThinkingBlock):
            return ThinkingDelta(
                thinking=_string(payload.get("thinking") or payload.get("text")),
                source_type=block.source_type,
                extras=_extras(payload, {"type", "thinking", "text"}),
            )
        return TextDelta(
            text=_string(payload.get("text")),
            extras=_extras(payload, {"type", "text"}),
        )

    if delta_type == "thinking_delta":
        return ThinkingDelta(
            thinking=_string(payload.get("thinking") or payload.get("text")),
            source_type="thinking",
            extras=_extras(payload, {"type", "thinking", "text"}),
        )

    if delta_type == "reasoning_delta":
        return ThinkingDelta(
            thinking=_string(payload.get("thinking") or payload.get("text")),
            source_type="reasoning",
            extras=_extras(payload, {"type", "thinking", "text"}),
        )

    if delta_type == "signature_delta":
        return SignatureDelta(
            signature=_string(payload.get("signature")),
            source_type=block.source_type if isinstance(block, ThinkingBlock) else "thinking",
            extras=_extras(payload, {"type", "signature"}),
        )

    if delta_type == "input_json_delta":
        return InputJsonDelta(
            partial_json=_string(payload.get("partial_json")),
            extras=_extras(payload, {"type", "partial_json"}),
        )

    return UnknownDelta(delta_type=delta_type, payload=dict(payload))


def delta_to_payload(delta: ContentDelta) -> dict[str, Any]:
    if isinstance(delta, TextDelta):
        return {"type": "text_delta", "text": delta.text, **dict(delta.extras)}
    if isinstance(delta, ThinkingDelta):
        return {"type": "thinking_delta", "thinking": delta.thinking, **dict(delta.extras)}
    if isinstance(delta, SignatureDelta):
        return {"type": "signature_delta", "signature": delta.signature, **dict(delta.extras)}
    if isinstance(delta, InputJsonDelta):
        return {"type": "input_json_delta", "partial_json": delta.partial_json, **dict(delta.extras)}
    if isinstance(delta, UnknownDelta):
        return dict(delta.payload)
    raise TypeError(f"unsupported delta: {type(delta)!r}")


def _string(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _int_or_none(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _extras(payload: Mapping[str, Any], excluded: set[str]) -> dict[str, Any]:
    return {key: value for key, value in payload.items() if key not in excluded}
