"""Central capability registry: alias resolution, MCP naming, category lookup."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from claude_proxy.capabilities.builtins import builtin_capability_records
from claude_proxy.capabilities.enums import BridgeImplementationStatus, CapabilityInventoryClass
from claude_proxy.capabilities.record import CapabilityRecord
from claude_proxy.domain.enums import ToolCategory
from claude_proxy.runtime.events import RuntimeEventKind


def is_mcp_style_tool_name(name_lower: str) -> bool:
    """Return True for ``mcp__<server>__<tool>`` names (tool segment may contain further ``__``)."""
    if not name_lower.startswith("mcp__"):
        return False
    parts = name_lower.split("__", 2)
    if len(parts) < 3:
        return False
    _mcp, server, tool_rest = parts[0], parts[1], parts[2]
    return _mcp == "mcp" and bool(server) and bool(tool_rest)


class CapabilityRegistry:
    """Authoritative tool-name resolution for the runtime bridge."""

    __slots__ = ("_by_alias", "_records")

    def __init__(self, records: tuple[CapabilityRecord, ...]) -> None:
        by_alias: dict[str, CapabilityRecord] = {}
        for rec in records:
            if rec.implementation_status is BridgeImplementationStatus.PARTIAL:
                if not (rec.residual_limitation and rec.residual_limitation.strip()):
                    raise ValueError(f"capability {rec.id!r} is PARTIAL but residual_limitation is empty")
            for key in rec.all_lookup_names():
                if key in by_alias and by_alias[key].id != rec.id:
                    msg = f"capability alias collision: {key!r} maps to {by_alias[key].id!r} and {rec.id!r}"
                    raise ValueError(msg)
                by_alias[key] = rec
        self._by_alias = by_alias
        self._records = records

    @property
    def records(self) -> tuple[CapabilityRecord, ...]:
        return self._records

    def resolve(self, name: str) -> CapabilityRecord | None:
        return self._by_alias.get(name.strip().lower())

    def classify_tool_category(self, name: str) -> ToolCategory:
        nl = name.strip().lower()
        if is_mcp_style_tool_name(nl):
            return ToolCategory.MCP
        rec = self._by_alias.get(nl)
        return rec.tool_category if rec is not None else ToolCategory.ORDINARY

    def triggers_abort(self, name: str) -> bool:
        rec = self.resolve(name)
        return bool(rec and rec.triggers_abort)

    def todo_write_text_signal(self, name: str) -> bool:
        rec = self.resolve(name)
        return bool(rec and rec.todo_write_text_signal)

    def control_runtime_event(self, name: str) -> RuntimeEventKind | None:
        """Map a state/control tool name to a model-derived runtime event, if any."""
        rec = self.resolve(name)
        if rec is None or rec.todo_write_text_signal or rec.triggers_abort:
            return None
        raw = rec.runtime_event_value
        if raw is None:
            return None
        try:
            return RuntimeEventKind(raw)
        except ValueError:
            return None

    def iter_by_inventory_class(self, cls: CapabilityInventoryClass) -> Iterator[CapabilityRecord]:
        for r in self._records:
            if r.inventory_class is cls:
                yield r


@lru_cache(maxsize=1)
def get_capability_registry() -> CapabilityRegistry:
    return CapabilityRegistry(builtin_capability_records())
