"""Unit tests for RuntimeContractEnforcer (application/runtime_contract.py)."""
from __future__ import annotations

import logging

import pytest

from claude_proxy.application.runtime_contract import RuntimeContractEnforcer
from claude_proxy.domain.enums import ActionPolicy, Role, RuntimeActionType, ThinkingPassthroughMode
from claude_proxy.domain.errors import RuntimeContractError
from claude_proxy.domain.models import ChatResponse, ModelInfo, TextBlock, ToolUseBlock, Usage


def _model(
    *,
    control_action_policy: ActionPolicy = ActionPolicy.ALLOW,
    orchestration_action_policy: ActionPolicy = ActionPolicy.ALLOW,
    generic_tool_emulation_policy: ActionPolicy = ActionPolicy.ALLOW,
) -> ModelInfo:
    return ModelInfo(
        name="test/model",
        provider="openrouter",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=False,
        thinking_passthrough_mode=ThinkingPassthroughMode.OFF,
        control_action_policy=control_action_policy,
        orchestration_action_policy=orchestration_action_policy,
        generic_tool_emulation_policy=generic_tool_emulation_policy,
    )


def _response(blocks: list) -> ChatResponse:
    return ChatResponse(
        id="msg_test",
        role=Role.ASSISTANT,
        model="test/model",
        content=tuple(blocks),
        stop_reason="tool_use",
        stop_sequence=None,
        usage=Usage(input_tokens=4, output_tokens=2),
    )


class TestRuntimeContractEnforcerAllow:
    enforcer = RuntimeContractEnforcer()

    def test_ordinary_tool_call_allowed_regardless(self) -> None:
        model = _model(generic_tool_emulation_policy=ActionPolicy.BLOCK)
        block = ToolUseBlock(id="tu_1", name="my_custom_tool", input={"x": 1})
        response = _response([block])
        result = self.enforcer.enforce_response(response, model)
        assert result is response  # identity preserved

    def test_text_block_ignored(self) -> None:
        model = _model()
        response = _response([TextBlock(text="hello")])
        result = self.enforcer.enforce_response(response, model)
        assert result is response

    def test_state_transition_allowed_when_policy_allow(self) -> None:
        model = _model(control_action_policy=ActionPolicy.ALLOW)
        block = ToolUseBlock(id="tu_1", name="TodoWrite", input={"todos": []})
        response = _response([block])
        # Must not raise
        self.enforcer.enforce_response(response, model)

    def test_orchestration_action_allowed_when_policy_allow(self) -> None:
        model = _model(orchestration_action_policy=ActionPolicy.ALLOW)
        block = ToolUseBlock(id="tu_1", name="Task", input={"description": "go"})
        response = _response([block])
        self.enforcer.enforce_response(response, model)


class TestRuntimeContractEnforcerBlock:
    enforcer = RuntimeContractEnforcer()

    def test_bash_echo_done_blocked_when_policy_block(self) -> None:
        model = _model(generic_tool_emulation_policy=ActionPolicy.BLOCK)
        block = ToolUseBlock(id="tu_1", name="bash", input={"command": "echo done"})
        response = _response([block])
        with pytest.raises(RuntimeContractError) as exc_info:
            self.enforcer.enforce_response(response, model)
        assert exc_info.value.status_code == 422

    def test_state_transition_blocked_when_policy_block(self) -> None:
        model = _model(control_action_policy=ActionPolicy.BLOCK)
        block = ToolUseBlock(id="tu_1", name="TodoWrite", input={})
        response = _response([block])
        with pytest.raises(RuntimeContractError):
            self.enforcer.enforce_response(response, model)

    def test_orchestration_action_blocked_when_policy_block(self) -> None:
        model = _model(orchestration_action_policy=ActionPolicy.BLOCK)
        block = ToolUseBlock(id="tu_1", name="Task", input={})
        response = _response([block])
        with pytest.raises(RuntimeContractError):
            self.enforcer.enforce_response(response, model)

    def test_runtime_contract_error_includes_tool_name(self) -> None:
        model = _model(generic_tool_emulation_policy=ActionPolicy.BLOCK)
        block = ToolUseBlock(id="tu_1", name="bash", input={"command": "echo done"})
        response = _response([block])
        with pytest.raises(RuntimeContractError) as exc_info:
            self.enforcer.enforce_response(response, model)
        assert exc_info.value.details.get("tool") == "bash"


class TestRuntimeContractEnforcerWarn:
    enforcer = RuntimeContractEnforcer()

    def test_bash_echo_done_warns_and_passes_when_policy_warn(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        model = _model(generic_tool_emulation_policy=ActionPolicy.WARN)
        block = ToolUseBlock(id="tu_1", name="bash", input={"command": "echo done"})
        response = _response([block])
        with caplog.at_level(logging.WARNING, logger="claude_proxy.contract"):
            result = self.enforcer.enforce_response(response, model)
        assert result is response
        assert any("runtime_contract_warn" in r.getMessage() for r in caplog.records)


class TestRuntimeContractEnforcerEnforceBlock:
    def test_enforce_tool_use_block_returns_action(self) -> None:
        enforcer = RuntimeContractEnforcer()
        model = _model(control_action_policy=ActionPolicy.ALLOW)
        block = ToolUseBlock(id="tu_1", name="TodoWrite", input={})
        action = enforcer.enforce_tool_use_block(block, model)
        assert action.action_type is RuntimeActionType.STATE_TRANSITION
