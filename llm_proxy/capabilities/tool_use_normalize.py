"""Deterministic repair/validation of tool *inputs* for SDK-shaped contracts (not JSON Schema)."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from typing import Any

from llm_proxy.capabilities.enums import SchemaContractKind
from llm_proxy.capabilities.record import CapabilityRecord
from llm_proxy.runtime.policies import InteractiveInputRepairMode

_logger = logging.getLogger("llm_proxy.capabilities")


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

    out = {k: v for k, v in base.items() if k not in ("questions", "answers")}
    out["questions"] = normalized_questions
    # answers must be a record (dict) or omitted; null / non-dict → drop it.
    answers = base.get("answers")
    if isinstance(answers, dict):
        out["answers"] = answers

    if repairs:
        _logger.debug(
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
        _logger.debug(
            "tool_input_repaired tool=ExitPlanMode repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "ExitPlanMode", "repairs": repairs}},
        )
    return out, repairs


def _str_to_bool(raw: str) -> bool:
    return raw.strip().lower() in ("true", "1", "yes", "on")


def normalize_todo_write_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Coerce ``todos`` to an array (models often emit a JSON string or a single object)."""
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("todo_write_input_not_object")
        repairs.append("input_coerced_to_object")
        base: dict[str, Any] = {"todos": [], "merge": True}
        return base, repairs

    out = dict(inp)
    raw = out.get("todos")

    if raw is None:
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("todo_write_missing_todos")
        out["todos"] = []
        repairs.append("todos_defaulted_empty")
    elif isinstance(raw, str):
        stripped = raw.strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            if mode is InteractiveInputRepairMode.STRICT:
                raise ValueError("todo_write_todos_invalid_json_string") from None
            out["todos"] = []
            repairs.append("todos_invalid_json_string_defaulted_empty")
        else:
            repairs.append("todos_parsed_from_json_string")
            if isinstance(parsed, list):
                out["todos"] = list(parsed)
            elif isinstance(parsed, dict):
                out["todos"] = [parsed]
                repairs.append("todos_wrapped_single_object")
            else:
                if mode is InteractiveInputRepairMode.STRICT:
                    raise ValueError("todo_write_todos_not_array_after_parse")
                out["todos"] = []
                repairs.append("todos_defaulted_empty_after_parse")
    elif isinstance(raw, dict):
        out["todos"] = [raw]
        repairs.append("todos_wrapped_single_object")
    elif isinstance(raw, list):
        out["todos"] = list(raw)
    else:
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("todo_write_todos_wrong_type")
        out["todos"] = []
        repairs.append("todos_coerced_empty_non_list")

    if "merge" in out and isinstance(out["merge"], str):
        out["merge"] = _str_to_bool(out["merge"])
        repairs.append("merge_coerced_from_string")

    if repairs:
        _logger.debug(
            "tool_input_repaired tool=TodoWrite repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "TodoWrite", "repairs": repairs}},
        )
    return out, repairs


def normalize_todo_read_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Coerce ``merge`` from string booleans when models emit JSON-incorrect types."""
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("todo_read_input_not_object")
        repairs.append("input_coerced_to_object")
        return {"merge": True}, repairs

    out = dict(inp)
    if "merge" in out and isinstance(out["merge"], str):
        out["merge"] = _str_to_bool(out["merge"])
        repairs.append("merge_coerced_from_string")

    if repairs:
        _logger.debug(
            "tool_input_repaired tool=TodoRead repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "TodoRead", "repairs": repairs}},
        )
    return out, repairs


def normalize_permission_request_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Parse ``permissions`` when provided as a JSON array string."""
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("permission_request_input_not_object")
        repairs.append("input_coerced_to_object")
        return {}, repairs

    out = dict(inp)
    perms = out.get("permissions")
    if isinstance(perms, str):
        stripped = perms.strip()
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            if mode is InteractiveInputRepairMode.STRICT:
                raise ValueError("permission_request_permissions_invalid_json") from None
            out["permissions"] = []
            repairs.append("permissions_invalid_json_defaulted_empty")
        else:
            repairs.append("permissions_parsed_from_json_string")
            if isinstance(parsed, list):
                out["permissions"] = parsed
            elif isinstance(parsed, dict):
                out["permissions"] = [parsed]
            else:
                if mode is InteractiveInputRepairMode.STRICT:
                    raise ValueError("permission_request_permissions_not_array_after_parse")
                out["permissions"] = []
                repairs.append("permissions_defaulted_empty_after_parse")

    if repairs:
        _logger.debug(
            "tool_input_repaired tool=request_permissions repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "request_permissions", "repairs": repairs}},
        )
    return out, repairs


def normalize_plan_enter_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Ensure object input; coerce common text fields to strings."""
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("plan_enter_input_not_object")
        repairs.append("input_coerced_to_object")
        return {}, repairs

    out = dict(inp)
    for key in ("plan", "reason", "message", "goal", "summary"):
        if key not in out or out[key] is None:
            continue
        val = out[key]
        if not isinstance(val, str):
            out[key] = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
            repairs.append(f"{key}_coerced_to_string")

    if repairs:
        _logger.debug(
            "tool_input_repaired tool=enter_plan_mode repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "enter_plan_mode", "repairs": repairs}},
        )
    return out, repairs


def normalize_orchestration_subagent_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Coerce string-typed fields models sometimes emit as numbers or nested JSON."""
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("orchestration_subagent_input_not_object")
        repairs.append("input_coerced_to_object")
        return {"prompt": "" if inp is None else str(inp)}, repairs

    out = dict(inp)
    string_keys = (
        "prompt",
        "description",
        "task",
        "subagent_type",
        "model",
        "instructions",
    )
    for key in string_keys:
        if key not in out or out[key] is None:
            continue
        val = out[key]
        if isinstance(val, str):
            continue
        out[key] = json.dumps(val) if isinstance(val, (dict, list)) else str(val)
        repairs.append(f"{key}_coerced_to_string")

    if repairs:
        _logger.debug(
            "tool_input_repaired tool=Agent repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "Agent", "repairs": repairs}},
        )
    return out, repairs


def normalize_bash_session_id_input(
    inp: Any,
    *,
    mode: InteractiveInputRepairMode,
) -> tuple[dict[str, Any], list[str]]:
    """Coerce ``bash_id`` / ``shell_id`` / ``session_id`` to strings (SDK expects string ids)."""
    repairs: list[str] = []
    if not isinstance(inp, dict):
        if mode is InteractiveInputRepairMode.STRICT:
            raise ValueError("bash_session_tool_input_not_object")
        repairs.append("input_coerced_to_object")
        return {}, repairs

    out = dict(inp)
    for key in ("bash_id", "shell_id", "session_id", "id"):
        if key not in out or out[key] is None:
            continue
        val = out[key]
        if isinstance(val, str):
            continue
        if isinstance(val, bool):
            raise ValueError("bash_session_id_invalid_type")
        out[key] = str(int(val)) if isinstance(val, float) and val == int(val) else str(val)
        repairs.append(f"{key}_coerced_to_string")

    if repairs:
        _logger.debug(
            "tool_input_repaired tool=bash_session repairs=%s",
            ",".join(repairs),
            extra={"extra_fields": {"tool": "bash_session", "repairs": repairs}},
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
    if record.schema_contract is SchemaContractKind.TODO_WRITE:
        return normalize_todo_write_input(tool_input, mode=mode)
    if record.schema_contract is SchemaContractKind.TODO_READ:
        return normalize_todo_read_input(tool_input, mode=mode)
    if record.schema_contract is SchemaContractKind.PERMISSION_REQUEST:
        return normalize_permission_request_input(tool_input, mode=mode)
    if record.schema_contract is SchemaContractKind.PLAN_ENTER:
        return normalize_plan_enter_input(tool_input, mode=mode)
    if record.schema_contract is SchemaContractKind.ORCHESTRATION_SUBAGENT:
        return normalize_orchestration_subagent_input(tool_input, mode=mode)
    if record.schema_contract is SchemaContractKind.BASH_SESSION_ID:
        return normalize_bash_session_id_input(tool_input, mode=mode)
    return tool_input, []


# ---------------------------------------------------------------------------
# Generic JSON-Schema-driven repair
# ---------------------------------------------------------------------------

_SCHEMA_TYPE_ZERO: dict[str, Any] = {
    "array": [],
    "object": {},
    "string": "",
    "number": 0,
    "integer": 0,
    "boolean": False,
}


def repair_from_schema(
    tool_input: Any,
    schema: Mapping[str, Any],
) -> tuple[Any, list[str]]:
    """Backfill missing *required* properties using JSON Schema defaults or zero-values.

    Designed as a universal fallback for tools not covered by SDK-specific
    normalizers.  Only touches top-level required properties that are absent
    or ``None``; never removes or restructures existing data.
    """
    if not isinstance(tool_input, dict):
        return tool_input, []

    properties: Mapping[str, Any] = schema.get("properties", {})
    required: Sequence[str] = schema.get("required", ())

    if not required or not properties:
        return tool_input, []

    repairs: list[str] = []
    patched = dict(tool_input)

    for key in required:
        prop_schema = properties.get(key)
        if prop_schema is None:
            continue
        current = patched.get(key, _SENTINEL)
        if current is not _SENTINEL and current is not None:
            continue
        # Use explicit default from schema, otherwise zero-value for the declared type.
        if "default" in prop_schema:
            patched[key] = prop_schema["default"]
            repairs.append(f"{key}_defaulted_from_schema")
        else:
            prop_type = prop_schema.get("type", "")
            zero = _SCHEMA_TYPE_ZERO.get(prop_type)
            if zero is not None:
                patched[key] = zero if not isinstance(zero, (list, dict)) else type(zero)()
                repairs.append(f"{key}_zero_filled_{prop_type}")

    return patched, repairs


_SENTINEL = object()
