"""Apply capability-aware normalization before runtime classification and client emission."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from dataclasses import replace

from claude_proxy.capabilities.enums import SchemaContractKind
from claude_proxy.capabilities.registry import get_capability_registry
from claude_proxy.capabilities.tool_use_normalize import apply_schema_contract
from claude_proxy.domain.models import (
    CanonicalEvent,
    ChatResponse,
    ContentBlockStartEvent,
    ToolUseBlock,
)
from claude_proxy.runtime.errors import InvalidToolSchemaContractError
from claude_proxy.runtime.policies import InteractiveInputRepairMode, RuntimeOrchestrationPolicies

_logger = logging.getLogger("claude_proxy.capabilities.outbound")


def _json_preview(obj: object, limit: int = 4000) -> str:
    try:
        s = json.dumps(obj, default=str, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        s = str(obj)
    return s if len(s) <= limit else f"{s[:limit]}...<truncated>"


def normalize_tool_use_for_runtime(
    block: ToolUseBlock,
    *,
    policies: RuntimeOrchestrationPolicies | None = None,
) -> ToolUseBlock:
    """Repair SDK-shaped tool inputs per :class:`RuntimeOrchestrationPolicies`.

    Unknown tools and MCP-style names are returned unchanged.
    """
    reg = get_capability_registry()
    rec = reg.resolve(block.name)
    if rec is None:
        return block
    mode = (
        policies.interactive_input_repair
        if policies is not None
        else InteractiveInputRepairMode.REPAIR
    )
    log_contract = rec.schema_contract is not SchemaContractKind.NONE and mode is not InteractiveInputRepairMode.FORWARD_RAW
    try:
        new_input, repairs = apply_schema_contract(record=rec, tool_input=block.input, mode=mode)
    except ValueError as exc:
        if log_contract:
            _logger.warning(
                "outbound_tool_contract_repair_failed",
                extra={
                    "extra_fields": {
                        "tool_use_name": block.name,
                        "capability_id": rec.id,
                        "canonical_name": rec.canonical_name,
                        "raw_input_preview": _json_preview(block.input),
                        "unrecoverable_reason": str(exc),
                    },
                },
            )
        raise InvalidToolSchemaContractError(
            str(exc),
            details={"tool": block.name, "contract": rec.schema_contract.value},
        ) from exc
    changed = new_input != block.input
    if log_contract:
        _logger.info(
            "outbound_tool_contract",
            extra={
                "extra_fields": {
                    "tool_use_name": block.name,
                    "capability_id": rec.id,
                    "canonical_name": rec.canonical_name,
                    "raw_input_preview": _json_preview(block.input),
                    "repaired": changed,
                    "repaired_input_preview": _json_preview(new_input) if changed else None,
                    "repair_tags": repairs,
                },
            },
        )
    if not changed:
        return block
    return replace(block, input=new_input)


def repair_chat_response_tool_blocks(
    response: ChatResponse,
    *,
    policies: RuntimeOrchestrationPolicies,
) -> ChatResponse:
    """Repair tool inputs on a normalized assistant message before contract enforcement / encoding."""
    changed = False
    new_blocks: list[object] = []
    for block in response.content:
        if isinstance(block, ToolUseBlock):
            nb = normalize_tool_use_for_runtime(block, policies=policies)
            if nb is not block:
                changed = True
            new_blocks.append(nb)
        else:
            new_blocks.append(block)
    if not changed:
        return response
    return replace(response, content=tuple(new_blocks))


async def repair_stream_tool_blocks(
    events: AsyncIterator[CanonicalEvent],
    *,
    policies: RuntimeOrchestrationPolicies,
) -> AsyncIterator[CanonicalEvent]:
    """Repair tool inputs on streamed content_block_start events (parity with non-stream)."""
    async for ev in events:
        if isinstance(ev, ContentBlockStartEvent) and isinstance(ev.block, ToolUseBlock):
            nb = normalize_tool_use_for_runtime(ev.block, policies=policies)
            if nb is not ev.block:
                ev = replace(ev, block=nb)
        yield ev
