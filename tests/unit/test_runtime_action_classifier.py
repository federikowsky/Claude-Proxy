"""Unit tests for RuntimeActionClassifier (application/runtime_actions.py)."""
from __future__ import annotations

import pytest

from claude_proxy.application.runtime_actions import RuntimeActionClassifier
from claude_proxy.domain.enums import RuntimeActionType, ToolCategory
from claude_proxy.domain.models import ToolUseBlock


def _block(name: str, tool_input: object = None) -> ToolUseBlock:
    return ToolUseBlock(id="tu_test", name=name, input=tool_input if tool_input is not None else {})


class TestRuntimeActionClassifierOrdinaryTools:
    clf = RuntimeActionClassifier()

    def test_ordinary_tool_is_tool_call(self) -> None:
        action = self.clf.classify(_block("my_custom_tool"))
        assert action.action_type is RuntimeActionType.TOOL_CALL

    def test_ordinary_tool_category_is_ordinary(self) -> None:
        action = self.clf.classify(_block("my_custom_tool"))
        assert action.tool_category is ToolCategory.ORDINARY

    def test_tool_name_preserved(self) -> None:
        action = self.clf.classify(_block("my_custom_tool"))
        assert action.tool_name == "my_custom_tool"


class TestRuntimeActionClassifierStateControl:
    clf = RuntimeActionClassifier()

    def test_todowrite_is_state_transition(self) -> None:
        action = self.clf.classify(_block("TodoWrite", {"todos": []}))
        assert action.action_type is RuntimeActionType.STATE_TRANSITION

    def test_exit_plan_mode_is_state_transition(self) -> None:
        action = self.clf.classify(_block("exit_plan_mode"))
        assert action.action_type is RuntimeActionType.STATE_TRANSITION

    def test_state_control_category(self) -> None:
        action = self.clf.classify(_block("TodoWrite", {}))
        assert action.tool_category is ToolCategory.STATE_CONTROL


class TestRuntimeActionClassifierOrchestration:
    clf = RuntimeActionClassifier()

    def test_task_is_orchestration_action(self) -> None:
        action = self.clf.classify(_block("Task", {"description": "do something"}))
        assert action.action_type is RuntimeActionType.ORCHESTRATION_ACTION

    def test_dispatch_agent_is_orchestration(self) -> None:
        action = self.clf.classify(_block("dispatch_agent"))
        assert action.action_type is RuntimeActionType.ORCHESTRATION_ACTION


class TestRuntimeActionClassifierGenericToolMisuse:
    clf = RuntimeActionClassifier()

    def test_bash_with_echo_done_is_invalid(self) -> None:
        action = self.clf.classify(_block("bash", {"command": "echo done"}))
        assert action.action_type is RuntimeActionType.INVALID_ACTION

    def test_bash_with_echo_complete_is_invalid(self) -> None:
        action = self.clf.classify(_block("bash", {"command": "echo complete"}))
        assert action.action_type is RuntimeActionType.INVALID_ACTION

    def test_bash_with_exit_0_is_invalid(self) -> None:
        action = self.clf.classify(_block("bash", {"command": "exit 0"}))
        assert action.action_type is RuntimeActionType.INVALID_ACTION

    def test_bash_with_echo_done_single_quote_is_invalid(self) -> None:
        action = self.clf.classify(_block("bash", {"command": "echo 'done'"}))
        assert action.action_type is RuntimeActionType.INVALID_ACTION

    def test_bash_with_normal_command_is_tool_call(self) -> None:
        action = self.clf.classify(_block("bash", {"command": "ls -la /tmp"}))
        assert action.action_type is RuntimeActionType.TOOL_CALL

    def test_bash_with_git_command_is_tool_call(self) -> None:
        action = self.clf.classify(_block("bash", {"command": "git status"}))
        assert action.action_type is RuntimeActionType.TOOL_CALL

    def test_bash_case_insensitive_classification(self) -> None:
        action = self.clf.classify(_block("Bash", {"command": "echo done"}))
        assert action.action_type is RuntimeActionType.INVALID_ACTION

    def test_generic_tool_with_done_key_is_finalization(self) -> None:
        action = self.clf.classify(_block("bash", {"done": True}))
        assert action.action_type is RuntimeActionType.FINALIZATION_ACTION

    def test_generic_tool_with_exit_key_is_finalization(self) -> None:
        action = self.clf.classify(_block("Read", {"exit": True}))
        assert action.action_type is RuntimeActionType.FINALIZATION_ACTION

    def test_bash_without_command_key_with_finalization_key_is_finalization(self) -> None:
        action = self.clf.classify(_block("bash", {"complete": True}))
        assert action.action_type is RuntimeActionType.FINALIZATION_ACTION


class TestRuntimeActionClassifierDiagnostics:
    clf = RuntimeActionClassifier()

    def test_invalid_action_has_diagnostic(self) -> None:
        action = self.clf.classify(_block("bash", {"command": "echo done"}))
        assert action.diagnostic  # non-empty

    def test_state_transition_has_diagnostic(self) -> None:
        action = self.clf.classify(_block("TodoWrite", {}))
        assert action.diagnostic
