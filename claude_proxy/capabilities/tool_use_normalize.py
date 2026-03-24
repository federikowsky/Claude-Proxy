"""Deterministic repair/validation of tool *inputs* for SDK-shaped contracts (not JSON Schema)."""

from __future__ import annotations

import json
import logging
from typing import Any

from claude_proxy.capabilities.enums import SchemaContractKind
from claude_proxy.capabilities.record import CapabilityRecord
from claude_proxy.runtime.policies import InteractiveInputRepairMode

_logger = logging.getLogger("claude_proxy.capabilities")


def _minimal_question(question_text: str) -> dict[str, Any]:
    return {
        "question": question_text,
        "header": "Question",
        "options": [
            {"label": "Yes", "description": "Proceed"},
            {"label": "No", "description": "Cancel"},
        ],
        "multiSelect": False,
    }


def _coerce_questions_array(raw: Any, repairs: list[str]) -> list[Any]:
    if raw is None:
        repairs.append("questions_defaulted_empty")
        return []
    if isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("["):
            try:
                parsed = json.loads(stripped)
                repairs.append("questions_parsed_from_json_string")
                if isinstance(parsed, list):
                    return list(parsed)
            except json.JSONDecodeError:
                repairs.append("questions_string_not_json_array_wrapped")
        return [_minimal_question(stripped)]
    if isinstance(raw, list):
        return list(raw)
    repairs.append("questions_replaced_from_non_list")
    return [_minimal_question(str(raw))]


def normalize_ask_user_question_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Normalize ``AskUserQuestion`` / ``ask_user`` shaped inputs toward SDK layout.

    Official contract (Agent SDK reference): top-level ``questions`` array (1–4 items),
    optional ``answers``. Legacy mistakes: missing ``questions``, lone ``question`` string,
    ``questions`` passed as a string.
    """
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("ask_user_question_input_not_object")
        repairs.append("input_coerced_to_object")
        base: dict[str, Any] = {}
    else:
        base = dict(inp)

    if "questions" not in base and "question" in base:
        q = base.pop("question")
        base["questions"] = [_minimal_question(str(q))]
        repairs.append("question_promoted_to_questions_array")

    questions_raw = base.get("questions")
    questions = _coerce_questions_array(questions_raw, repairs)
    if not questions:
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("ask_user_question_missing_questions")
        questions = [_minimal_question("Continue?")]
        repairs.append("questions_defaulted_placeholder")

    normalized_questions: list[dict[str, Any]] = []
    for item in questions[:4]:
        if isinstance(item, dict) and isinstance(item.get("question"), str):
            normalized_questions.append(item)
            continue
        if isinstance(item, str):
            normalized_questions.append(_minimal_question(item))
            repairs.append("question_item_wrapped_from_string")
            continue
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("ask_user_question_malformed_question_item")
        normalized_questions.append(_minimal_question(str(item)))
        repairs.append("question_item_coerced")

    out = {k: v for k, v in base.items() if k != "questions"}
    out["questions"] = normalized_questions
    if "answers" in base:
        out["answers"] = base["answers"]
    else:
        out["answers"] = None

    if repairs:
        _logger.info(
            "tool_input_repaired tool=AskUserQuestion repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "AskUserQuestion", "repairs": repairs}},
        )
    return out, repairs


def normalize_exit_plan_mode_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Ensure ``ExitPlanMode`` carries a string ``plan`` field (SDK reference)."""
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("exit_plan_mode_input_not_object")
        repairs.append("input_coerced_to_object")
        out: dict[str, Any] = {"plan": ""}
    else:
        out = dict(inp)
        plan = out.get("plan")
        if not isinstance(plan, str):
            if mode is InteractiveInputRepairMode.STRICT:
                raise ValueError("exit_plan_mode_missing_plan_string")
            out["plan"] = "" if plan is None else str(plan)
            repairs.append("plan_coerced_to_string")
    if repairs:
        _logger.info(
            "tool_input_repaired tool=ExitPlanMode repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "ExitPlanMode", "repairs": repairs}},
        )
    return out, repairs


def apply_schema_contract(
    *,
    record: CapabilityRecord,
    tool_input: Any,
    mode: InteractiveInputRepairMode,
) -> tuple[Any, list[str]]:
    """Return (possibly repaired input, repair tags). FORWARD_RAW leaves input unchanged."""
    if mode is InteractiveInputRepairMode.FORWARD_RAW:
        return tool_input, []
    if record.schema_contract is SchemaContractKind.NONE:
        return tool_input, []
    if record.schema_contract is SchemaContractKind.INTERACTIVE_QUESTION:
        return normalize_ask_user_question_input(tool_input, mode=mode)
    if record.schema_contract is SchemaContractKind.EXIT_PLAN:
        return normalize_exit_plan_mode_input(tool_input, mode=mode)
    return tool_input, []
