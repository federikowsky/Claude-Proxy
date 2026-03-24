"""Formal closure for inventory families that are not tool-registry rows."""

from __future__ import annotations

from dataclasses import dataclass

from claude_proxy.capabilities.enums import RuntimeFamilyClosureStatus


@dataclass(frozen=True, slots=True)
class InventoryFamilyClosure:
    family_id: str
    status: RuntimeFamilyClosureStatus
    rationale: str


NON_TOOL_FAMILY_CLOSURE: tuple[InventoryFamilyClosure, ...] = (
    InventoryFamilyClosure(
        family_id="hooks",
        status=RuntimeFamilyClosureStatus.BLOCKED_BY_MISSING_WIRE_CONTRACT,
        rationale="Hook events (PreToolUse, PostToolUse, …) require a normalized event stream in the proxy; not present.",
    ),
    InventoryFamilyClosure(
        family_id="runtime_system_messages",
        status=RuntimeFamilyClosureStatus.BLOCKED_BY_MISSING_WIRE_CONTRACT,
        rationale="TaskStartedMessage / TaskProgressMessage wire shapes are not modeled as canonical events in this repository.",
    ),
    InventoryFamilyClosure(
        family_id="worktree",
        status=RuntimeFamilyClosureStatus.EXPLICITLY_OUT_OF_SCOPE,
        rationale="WorktreeCreate/Remove are host/CLI concerns; no stable proxy API or message mapping exists here.",
    ),
    InventoryFamilyClosure(
        family_id="remote",
        status=RuntimeFamilyClosureStatus.EXPLICITLY_OUT_OF_SCOPE,
        rationale="Remote agent/control flags are CLI/session configuration, not translated through this HTTP bridge.",
    ),
    InventoryFamilyClosure(
        family_id="teammate",
        status=RuntimeFamilyClosureStatus.EXPLICITLY_OUT_OF_SCOPE,
        rationale="Teammate mode is a Claude Code product surface without a dedicated proxy protocol in this repo.",
    ),
    InventoryFamilyClosure(
        family_id="background_task_progress",
        status=RuntimeFamilyClosureStatus.INVENTORY_ONLY,
        rationale="Progress surfaces are documented for parity; only ordinary tool forward + runtime orchestration apply where tools exist.",
    ),
)
