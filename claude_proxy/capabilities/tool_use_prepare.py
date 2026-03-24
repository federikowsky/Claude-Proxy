"""Apply capability-aware normalization before runtime classification."""

from __future__ import annotations

from dataclasses import replace

from claude_proxy.capabilities.registry import get_capability_registry
from claude_proxy.capabilities.tool_use_normalize import apply_schema_contract
from claude_proxy.domain.models import ToolUseBlock
from claude_proxy.runtime.errors import InvalidToolSchemaContractError
from claude_proxy.runtime.policies import InteractiveInputRepairMode, RuntimeOrchestrationPolicies


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
    try:
        new_input, _repairs = apply_schema_contract(record=rec, tool_input=block.input, mode=mode)
    except ValueError as exc:
        raise InvalidToolSchemaContractError(
            str(exc),
            details={"tool": block.name, "contract": rec.schema_contract.value},
        ) from exc
    if new_input is block.input:
        return block
    return replace(block, input=new_input)
