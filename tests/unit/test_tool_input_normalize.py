from __future__ import annotations

import pytest

from claude_proxy.capabilities.tool_use_normalize import (
    normalize_ask_user_question_input,
    normalize_exit_plan_mode_input,
)
from claude_proxy.runtime.policies import InteractiveInputRepairMode


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
