from __future__ import annotations

from claude_proxy.domain.models import ToolUseBlock
from claude_proxy.runtime.classifier import RuntimeModelClassifier
from claude_proxy.runtime.events import RuntimeEventKind


def test_classify_ordinary_domain_tool() -> None:
    c = RuntimeModelClassifier()
    b = ToolUseBlock(id="1", name="my_api_tool", input={})
    m = c.classify_tool_use(b)
    assert m.event_kind is RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED
    assert m.forward_ordinary_tool is True


def test_classify_exit_plan() -> None:
    c = RuntimeModelClassifier()
    b = ToolUseBlock(id="1", name="exit_plan_mode", input={})
    m = c.classify_tool_use(b)
    assert m.event_kind is RuntimeEventKind.MODEL_EXIT_PLAN_PROPOSED
    assert m.forward_ordinary_tool is False


def test_classify_subtask() -> None:
    c = RuntimeModelClassifier()
    b = ToolUseBlock(id="1", name="Task", input={"description": "x"})
    m = c.classify_tool_use(b)
    assert m.event_kind is RuntimeEventKind.MODEL_START_SUBTASK_PROPOSED
    assert m.forward_ordinary_tool is False


def test_classify_todowrite_maps_to_text_signal() -> None:
    c = RuntimeModelClassifier()
    b = ToolUseBlock(id="1", name="TodoWrite", input={"todos": []})
    m = c.classify_tool_use(b)
    assert m.event_kind is RuntimeEventKind.MODEL_TEXT_EMITTED
