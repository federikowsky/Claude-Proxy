from __future__ import annotations

import json

import pytest

from llm_proxy.capabilities.tool_use_normalize import (
    normalize_ask_user_question_input,
    normalize_bash_session_id_input,
    normalize_exit_plan_mode_input,
    normalize_orchestration_subagent_input,
    normalize_permission_request_input,
    normalize_plan_enter_input,
    normalize_todo_read_input,
    normalize_todo_write_input,
)
from llm_proxy.runtime.policies import InteractiveInputRepairMode


def test_ask_user_promotes_legacy_question_field() -> None:
    out, repairs = normalize_ask_user_question_input(
        {"question": "Proceed?"},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert "questions" in out
    assert len(out["questions"]) == 1
    assert out["questions"][0]["question"] == "Proceed?"
    assert repairs


def test_ask_user_repairs_questions_json_string() -> None:
    raw = '{"question": "X", "header": "H", "options": [{"label": "a", "description": "b"}, {"label": "c", "description": "d"}], "multiSelect": false}'
    out, _ = normalize_ask_user_question_input(
        {"questions": f'[{raw}]'},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert isinstance(out["questions"], list)
    assert out["questions"][0]["question"] == "X"


def test_ask_user_strict_rejects_non_object() -> None:
    with pytest.raises(ValueError, match="ask_user_question_input_not_object"):
        normalize_ask_user_question_input("nope", mode=InteractiveInputRepairMode.STRICT)


def test_exit_plan_strict_requires_plan_string() -> None:
    with pytest.raises(ValueError, match="exit_plan_mode_missing_plan_string"):
        normalize_exit_plan_mode_input({"plan": 1}, mode=InteractiveInputRepairMode.STRICT)


def test_exit_plan_repair_coerces_plan() -> None:
    out, repairs = normalize_exit_plan_mode_input({"plan": 3}, mode=InteractiveInputRepairMode.REPAIR)
    assert out["plan"] == "3"
    assert repairs


def test_todo_write_repairs_todos_json_string() -> None:
    item = {"content": "a", "status": "pending", "activeForm": "Doing a"}
    raw = json.dumps([item])
    out, repairs = normalize_todo_write_input(
        {"todos": raw, "merge": True},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert isinstance(out["todos"], list)
    assert out["todos"][0]["content"] == "a"
    assert repairs


def test_todo_write_wraps_single_object_as_one_element_array() -> None:
    out, repairs = normalize_todo_write_input(
        {"todos": {"content": "x", "status": "pending", "activeForm": "X"}},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert len(out["todos"]) == 1
    assert out["todos"][0]["content"] == "x"
    assert repairs


def test_todo_write_merge_string_coerced() -> None:
    out, repairs = normalize_todo_write_input(
        {"todos": [], "merge": "false"},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert out["merge"] is False
    assert repairs


def test_todo_write_strict_missing_todos() -> None:
    with pytest.raises(ValueError, match="todo_write_missing_todos"):
        normalize_todo_write_input({"merge": True}, mode=InteractiveInputRepairMode.STRICT)


def test_todo_read_merge_string_coerced() -> None:
    out, repairs = normalize_todo_read_input({"merge": "yes"}, mode=InteractiveInputRepairMode.REPAIR)
    assert out["merge"] is True
    assert repairs


def test_permission_request_permissions_json_string() -> None:
    out, repairs = normalize_permission_request_input(
        {"permissions": '[{"type":"network"}]'},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert isinstance(out["permissions"], list)
    assert repairs


def test_plan_enter_coerces_numeric_reason() -> None:
    out, repairs = normalize_plan_enter_input({"reason": 42}, mode=InteractiveInputRepairMode.REPAIR)
    assert out["reason"] == "42"
    assert repairs


def test_orchestration_subagent_prompt_object_to_json_string() -> None:
    out, repairs = normalize_orchestration_subagent_input(
        {"prompt": {"goal": "fix bug"}, "subagent_type": "general"},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert json.loads(out["prompt"]) == {"goal": "fix bug"}
    assert out["subagent_type"] == "general"
    assert repairs


def test_bash_output_bash_id_int_to_string() -> None:
    out, repairs = normalize_bash_session_id_input(
        {"bash_id": 7},
        mode=InteractiveInputRepairMode.REPAIR,
    )
    assert out["bash_id"] == "7"
    assert repairs


def test_bash_session_rejects_bool_id() -> None:
    with pytest.raises(ValueError, match="bash_session_id_invalid_type"):
        normalize_bash_session_id_input({"bash_id": True}, mode=InteractiveInputRepairMode.REPAIR)
