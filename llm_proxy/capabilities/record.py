"""Frozen capability descriptor row (single source for classification metadata)."""

from __future__ import annotations

from dataclasses import dataclass

from llm_proxy.capabilities.enums import (
    BridgeImplementationStatus,
    CapabilityInventoryClass,
    EvidenceTier,
    SchemaContractKind,
)
from llm_proxy.domain.enums import ToolCategory


@dataclass(frozen=True, slots=True)
class CapabilityRecord:
    """Authoritative metadata for one logical Claude Code / SDK capability surface.

    Aliases are stored **lowercase** for deterministic lookup. ``canonical_name`` preserves
    SDK-style casing for documentation and telemetry.
    """

    id: str
    canonical_name: str
    aliases: frozenset[str]
    inventory_class: CapabilityInventoryClass
    evidence_tier: EvidenceTier
    tool_category: ToolCategory
    runtime_event_value: str | None = None
    triggers_abort: bool = False
    todo_write_text_signal: bool = False
    schema_contract: SchemaContractKind = SchemaContractKind.NONE
    implementation_status: BridgeImplementationStatus = BridgeImplementationStatus.IMPLEMENTED
    residual_limitation: str | None = None

    def all_lookup_names(self) -> frozenset[str]:
        base = self.canonical_name.lower()
        return frozenset({base, *self.aliases})
