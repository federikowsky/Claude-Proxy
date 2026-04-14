"""Apply capability-aware normalization before runtime classification and client emission."""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from dataclasses import replace

from llm_proxy.capabilities.enums import SchemaContractKind
from llm_proxy.capabilities.registry import get_capability_registry
from llm_proxy.capabilities.tool_use_normalize import apply_schema_contract, repair_from_schema
from llm_proxy.domain.models import (
    CanonicalEvent,
    ChatResponse,
    ContentBlockDeltaEvent,
    ContentBlockStartEvent,
    ContentBlockStopEvent,
    InputJsonDelta,
    ToolUseBlock,
)
from llm_proxy.runtime.errors import InvalidToolSchemaContractError
from llm_proxy.runtime.policies import InteractiveInputRepairMode, RuntimeOrchestrationPolicies

_logger = logging.getLogger("llm_proxy.capabilities.outbound")

# name → JSON Schema mapping, built from request tool definitions.
ToolSchemaLookup = Mapping[str, Mapping[str, object]]


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
    tool_schemas: ToolSchemaLookup | None = None,
) -> ToolUseBlock:
    """Repair SDK-shaped tool inputs per :class:`RuntimeOrchestrationPolicies`.

    For tools with a dedicated SDK normalizer the specific contract is used.
    For all other tools whose ``input_schema`` was supplied in the request,
    :func:`repair_from_schema` backfills missing required properties.
    """
    reg = get_capability_registry()
    rec = reg.resolve(block.name)
    mode = (
        policies.interactive_input_repair
        if policies is not None
        else InteractiveInputRepairMode.REPAIR
    )
    schema = None if tool_schemas is None else tool_schemas.get(block.name)

    if rec is not None:
        # --- SDK-specific normalizer path (existing) ---
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
        if changed:
            return replace(block, input=new_input)
        # Registry-known tools without a dedicated contract still benefit from
        # generic schema-driven repair (for example Read.file_path).
        if rec.schema_contract is not SchemaContractKind.NONE:
            return block

    # --- Generic schema-driven fallback ---
    if mode is InteractiveInputRepairMode.FORWARD_RAW or schema is None:
        return block
    new_input, repairs = repair_from_schema(block.input, schema)
    if not repairs:
        return block
    _logger.info(
        "outbound_tool_schema_repair",
        extra={
            "extra_fields": {
                "tool_use_name": block.name,
                "raw_input_preview": _json_preview(block.input),
                "repaired_input_preview": _json_preview(new_input),
                "repair_tags": repairs,
            },
        },
    )
    return replace(block, input=new_input)


def repair_chat_response_tool_blocks(
    response: ChatResponse,
    *,
    policies: RuntimeOrchestrationPolicies,
    tool_schemas: ToolSchemaLookup | None = None,
) -> ChatResponse:
    """Repair tool inputs on a normalized assistant message before contract enforcement / encoding."""
    changed = False
    new_blocks: list[object] = []
    for block in response.content:
        if isinstance(block, ToolUseBlock):
            nb = normalize_tool_use_for_runtime(block, policies=policies, tool_schemas=tool_schemas)
            if nb is not block:
                changed = True
            new_blocks.append(nb)
        else:
            new_blocks.append(block)
    if not changed:
        return response
    return replace(response, content=tuple(new_blocks))


def _flush_tool_buffer(
    index: int,
    start_ev: ContentBlockStartEvent,
    chunks: list[str],
    policies: RuntimeOrchestrationPolicies,
    tool_schemas: ToolSchemaLookup | None = None,
) -> Sequence[CanonicalEvent]:
    """Reconstruct + repair a buffered tool block and return events to emit."""
    block = start_ev.block
    assert isinstance(block, ToolUseBlock)

    if chunks:
        raw_json = "".join(chunks)
        try:
            full_input = json.loads(raw_json)
        except (json.JSONDecodeError, ValueError):
            return [start_ev] + [
                ContentBlockDeltaEvent(index=index, delta=InputJsonDelta(partial_json=c))
                for c in chunks
            ]
        repaired = normalize_tool_use_for_runtime(
            replace(block, input=full_input), policies=policies, tool_schemas=tool_schemas,
        )
        return [
            start_ev,
            ContentBlockDeltaEvent(
                index=index,
                delta=InputJsonDelta(
                    partial_json=json.dumps(
                        repaired.input, separators=(",", ":"), ensure_ascii=False,
                    ),
                ),
            ),
        ]

    # Anthropic-native path: full input is in start event.
    repaired = normalize_tool_use_for_runtime(block, policies=policies, tool_schemas=tool_schemas)
    if repaired is not block:
        return [replace(start_ev, block=repaired)]
    return [start_ev]


async def repair_stream_tool_blocks(
    events: AsyncIterator[CanonicalEvent],
    *,
    policies: RuntimeOrchestrationPolicies,
    tool_schemas: ToolSchemaLookup | None = None,
) -> AsyncIterator[CanonicalEvent]:
    """Buffer tool_use input deltas for repairable tools, fix input, and re-emit.

    Two upstream formats exist:

    * **Anthropic-native** — full input in ``content_block_start``, no deltas.
      Repair is applied directly on the start event.
    * **OpenAI-compat** — ``input: {}`` placeholder in start, real input via
      ``input_json_delta`` events.  Deltas are buffered, the full input is
      reconstructed at ``content_block_stop``, repaired, and re-emitted as a
      single corrected delta.

    Tools are buffered when they are either known to the capability registry
    (SDK-specific repair) **or** have a matching ``input_schema`` in
    *tool_schemas* (generic schema repair).
    """
    reg = get_capability_registry()
    # index → (start_event, accumulated partial_json chunks)
    buffered: dict[int, tuple[ContentBlockStartEvent, list[str]]] = {}

    def _should_buffer(name: str) -> bool:
        if reg.resolve(name) is not None:
            return True
        return tool_schemas is not None and name in tool_schemas

    async for ev in events:
        # --- tool_use block start: hold back for potential repair ---
        if isinstance(ev, ContentBlockStartEvent) and isinstance(ev.block, ToolUseBlock):
            if _should_buffer(ev.block.name):
                buffered[ev.index] = (ev, [])
                continue  # don't yield yet — flushed at block stop
            yield ev
            continue

        # --- input delta for a buffered tool: collect, don't forward yet ---
        if (
            isinstance(ev, ContentBlockDeltaEvent)
            and isinstance(ev.delta, InputJsonDelta)
            and ev.index in buffered
        ):
            buffered[ev.index][1].append(ev.delta.partial_json)
            continue

        # --- block stop for a buffered tool: repair and flush ---
        if isinstance(ev, ContentBlockStopEvent) and ev.index in buffered:
            start_ev, chunks = buffered.pop(ev.index)
            for flushed in _flush_tool_buffer(ev.index, start_ev, chunks, policies, tool_schemas):
                yield flushed
            yield ev
            continue

        yield ev

    # Flush any remaining buffered start events (stream ended without stop).
    for index, (start_ev, chunks) in buffered.items():
        for flushed in _flush_tool_buffer(index, start_ev, chunks, policies, tool_schemas):
            yield flushed
