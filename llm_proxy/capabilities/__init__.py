"""Central capability inventory and registry for the Claude Code / Agent SDK runtime bridge."""

from __future__ import annotations

from typing import Any

__all__ = [
    "CapabilityRegistry",
    "get_capability_registry",
    "normalize_tool_use_for_runtime",
]


def __getattr__(name: str) -> Any:
    if name == "CapabilityRegistry":
        from llm_proxy.capabilities.registry import CapabilityRegistry

        return CapabilityRegistry
    if name == "get_capability_registry":
        from llm_proxy.capabilities.registry import get_capability_registry

        return get_capability_registry
    if name == "normalize_tool_use_for_runtime":
        from llm_proxy.capabilities.tool_use_prepare import normalize_tool_use_for_runtime

        return normalize_tool_use_for_runtime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
