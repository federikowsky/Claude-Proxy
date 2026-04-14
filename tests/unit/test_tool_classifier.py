"""Unit tests for the ToolClassifier."""
from __future__ import annotations

import pytest

from llm_proxy.application.tool_classifier import (
    GENERIC_TOOL_NAMES,
    ORCHESTRATION_TOOL_NAMES,
    STATE_CONTROL_TOOL_NAMES,
    ToolClassifier,
    get_default_classifier,
)
from llm_proxy.domain.enums import ToolCategory
from llm_proxy.domain.models import ToolDefinition


def _tool(name: str) -> ToolDefinition:
    return ToolDefinition(name=name, description=None, input_schema={"type": "object", "properties": {}})


class TestToolClassifierByCategory:
    clf = ToolClassifier()

    def test_bash_is_generic(self) -> None:
        assert self.clf.classify(_tool("bash")) is ToolCategory.GENERIC

    def test_bash_case_insensitive(self) -> None:
        assert self.clf.classify(_tool("Bash")) is ToolCategory.GENERIC
        assert self.clf.classify(_tool("BASH")) is ToolCategory.GENERIC

    def test_read_is_generic(self) -> None:
        assert self.clf.classify(_tool("Read")) is ToolCategory.GENERIC

    def test_write_is_generic(self) -> None:
        assert self.clf.classify(_tool("Write")) is ToolCategory.GENERIC

    def test_todowrite_is_state_control(self) -> None:
        assert self.clf.classify(_tool("TodoWrite")) is ToolCategory.STATE_CONTROL

    def test_exit_plan_mode_is_state_control(self) -> None:
        assert self.clf.classify(_tool("exit_plan_mode")) is ToolCategory.STATE_CONTROL

    def test_ask_user_is_state_control(self) -> None:
        assert self.clf.classify(_tool("ask_user")) is ToolCategory.STATE_CONTROL

    def test_permission_request_is_state_control(self) -> None:
        assert self.clf.classify(_tool("permission_request")) is ToolCategory.STATE_CONTROL

    def test_task_is_orchestration(self) -> None:
        assert self.clf.classify(_tool("Task")) is ToolCategory.ORCHESTRATION

    def test_dispatch_agent_is_orchestration(self) -> None:
        assert self.clf.classify(_tool("dispatch_agent")) is ToolCategory.ORCHESTRATION

    def test_unknown_tool_is_ordinary(self) -> None:
        assert self.clf.classify(_tool("my_custom_tool")) is ToolCategory.ORDINARY

    def test_classify_by_name_matches_classify(self) -> None:
        clf = ToolClassifier()
        for name in ["bash", "TodoWrite", "Task", "my_tool"]:
            tool = _tool(name)
            assert clf.classify_by_name(name) is clf.classify(tool)


class TestToolClassifierAnnotate:
    clf = ToolClassifier()

    def test_annotate_sets_category(self) -> None:
        tool = _tool("bash")
        annotated = self.clf.annotate(tool)
        assert annotated.category is ToolCategory.GENERIC

    def test_annotate_preserves_identity_when_category_correct(self) -> None:
        from dataclasses import replace

        tool = replace(_tool("bash"), category=ToolCategory.GENERIC)
        annotated = self.clf.annotate(tool)
        assert annotated is tool  # identity preserved

    def test_annotate_all_preserves_tuple_identity_when_no_changes(self) -> None:
        from dataclasses import replace

        tools = (
            replace(_tool("bash"), category=ToolCategory.GENERIC),
            replace(_tool("TodoWrite"), category=ToolCategory.STATE_CONTROL),
        )
        result = self.clf.annotate_all(tools)
        assert result is tools  # identity preserved


class TestToolClassifierSingleton:
    def test_get_default_classifier_returns_same_instance(self) -> None:
        a = get_default_classifier()
        b = get_default_classifier()
        assert a is b


class TestToolNameSets:
    def test_all_sets_are_disjoint(self) -> None:
        assert GENERIC_TOOL_NAMES.isdisjoint(STATE_CONTROL_TOOL_NAMES)
        assert GENERIC_TOOL_NAMES.isdisjoint(ORCHESTRATION_TOOL_NAMES)
        assert STATE_CONTROL_TOOL_NAMES.isdisjoint(ORCHESTRATION_TOOL_NAMES)

    def test_known_generic_names_present(self) -> None:
        for name in {"bash", "read", "write", "edit"}:
            assert name in GENERIC_TOOL_NAMES, f"{name!r} missing from GENERIC_TOOL_NAMES"
