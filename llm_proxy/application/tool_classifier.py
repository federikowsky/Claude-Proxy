"""Tool classification layer — names resolved via :mod:`llm_proxy.capabilities.registry`."""

from __future__ import annotations

from llm_proxy.capabilities.registry import get_capability_registry
from llm_proxy.domain.enums import ToolCategory
from llm_proxy.domain.models import ToolDefinition


def _names_for_category(category: ToolCategory) -> frozenset[str]:
    reg = get_capability_registry()
    acc: set[str] = set()
    for rec in reg.records:
        if rec.tool_category is category:
            acc.update(rec.all_lookup_names())
    return frozenset(acc)


# Derived from the capability registry (used by tests and diagnostics).
GENERIC_TOOL_NAMES: frozenset[str] = _names_for_category(ToolCategory.GENERIC)
STATE_CONTROL_TOOL_NAMES: frozenset[str] = _names_for_category(ToolCategory.STATE_CONTROL)
ORCHESTRATION_TOOL_NAMES: frozenset[str] = _names_for_category(ToolCategory.ORCHESTRATION)


class ToolClassifier:
    """Classify :class:`ToolDefinition` objects into :class:`~ToolCategory` buckets."""

    def classify(self, tool: ToolDefinition) -> ToolCategory:
        return self.classify_by_name(tool.name)

    def classify_by_name(self, name: str) -> ToolCategory:
        return get_capability_registry().classify_tool_category(name)

    def annotate(self, tool: ToolDefinition) -> ToolDefinition:
        category = self.classify(tool)
        if tool.category is category:
            return tool
        from dataclasses import replace

        return replace(tool, category=category)

    def annotate_all(
        self, tools: tuple[ToolDefinition, ...]
    ) -> tuple[ToolDefinition, ...]:
        annotated = tuple(self.annotate(t) for t in tools)
        if all(a is b for a, b in zip(annotated, tools, strict=True)):
            return tools
        return annotated


_default_classifier = ToolClassifier()


def get_default_classifier() -> ToolClassifier:
    return _default_classifier
