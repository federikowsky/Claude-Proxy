"""Executable capability coverage: derived from the registry + static test manifest."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from llm_proxy.capabilities.enums import BridgeImplementationStatus, SchemaContractKind
from llm_proxy.capabilities.families import NON_TOOL_FAMILY_CLOSURE
from llm_proxy.capabilities.record import CapabilityRecord
from llm_proxy.capabilities.registry import get_capability_registry, is_mcp_style_tool_name

# Every registry id must appear here so adding a row without tests fails CI.
REQUIRED_TESTS_BY_CAPABILITY_ID: dict[str, tuple[str, ...]] = {
    "interactive_ask_user_question": ("unit:test_capability_registry", "unit:test_tool_input_normalize", "integration:e2e_flows"),
    "permission_request_sdk": ("unit:test_capability_registry", "integration:e2e_flows"),
    "plan_exit_exit_plan_mode": ("unit:test_capability_registry", "unit:test_tool_input_normalize", "unit:runtime_classifier"),
    "plan_enter": ("unit:test_capability_registry", "unit:runtime_classifier"),
    "plan_todo_write": ("unit:test_capability_registry", "integration:orchestration"),
    "builtin_todo_read": ("unit:test_capability_registry",),
    "orchestration_subagent": ("unit:test_capability_registry", "unit:runtime_action_classifier", "integration:e2e_flows"),
    "session_abort_tool": ("unit:test_capability_registry", "integration:e2e_flows"),
    "builtin_bash": ("unit:test_runtime_action_classifier", "integration:orchestration"),
    "builtin_computer": ("unit:test_capability_registry",),
    "builtin_read": ("unit:test_runtime_action_classifier", "integration:orchestration"),
    "builtin_write": ("unit:test_capability_registry",),
    "builtin_edit": ("unit:test_capability_registry",),
    "builtin_glob": ("unit:test_capability_registry",),
    "builtin_grep": ("unit:test_capability_registry",),
    "builtin_ls": ("unit:test_capability_registry",),
    "builtin_notebook": ("unit:test_capability_registry",),
    "builtin_webfetch": ("unit:test_capability_registry",),
    "builtin_websearch": ("unit:test_capability_registry",),
    "builtin_screenshot": ("unit:test_capability_registry",),
    "builtin_bash_output": ("unit:test_capability_registry",),
    "builtin_kill_bash": ("unit:test_capability_registry",),
    "mcp_list_resources": ("unit:test_capability_registry",),
    "mcp_read_resource": ("unit:test_capability_registry",),
    "host_record_thinking": ("unit:test_capability_registry",),
    "host_set_env": ("unit:test_capability_registry",),
    "host_clear_env": ("unit:test_capability_registry",),
}

MCP_PATTERN_ROW_ID = "mcp__dynamic_pattern"


@dataclass(frozen=True, slots=True)
class CoverageRow:
    capability_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    evidence_tier: str
    recognized: bool
    normalized: str
    classified: bool
    runtime_event_value: str | None
    stream_support: bool
    non_stream_support: bool
    forward_or_consume: str
    control_api: str
    persisted: str
    replayed: str
    policy_governed: bool
    tests: tuple[str, ...]
    implementation_status: str
    residual_limitation: str | None


def _forward_consume(rec: CapabilityRecord) -> str:
    if rec.todo_write_text_signal or rec.triggers_abort:
        return "consumed"
    if rec.tool_category.value == "orchestration":
        return "consumed"
    if rec.runtime_event_value:
        return "consumed"
    if rec.tool_category.value in ("generic", "ordinary", "mcp"):
        return "forwarded"
    return "forwarded"


def _normalized(rec: CapabilityRecord) -> str:
    if rec.schema_contract is not SchemaContractKind.NONE:
        return "yes"
    return "not_applicable"


def row_for_record(rec: CapabilityRecord) -> CoverageRow:
    tests = REQUIRED_TESTS_BY_CAPABILITY_ID.get(rec.id, ())
    control_api = "yes" if (rec.runtime_event_value or rec.triggers_abort) else "not_applicable"
    return CoverageRow(
        capability_id=rec.id,
        canonical_name=rec.canonical_name,
        aliases=tuple(sorted(rec.all_lookup_names())),
        evidence_tier=rec.evidence_tier.value,
        recognized=True,
        normalized=_normalized(rec),
        classified=True,
        runtime_event_value=rec.runtime_event_value,
        stream_support=True,
        non_stream_support=True,
        forward_or_consume=_forward_consume(rec),
        control_api=control_api,
        persisted="when_orchestration_enabled",
        replayed="when_orchestration_enabled",
        policy_governed=True,
        tests=tests,
        implementation_status=rec.implementation_status.value,
        residual_limitation=rec.residual_limitation,
    )


def mcp_pattern_row() -> CoverageRow:
    return CoverageRow(
        capability_id=MCP_PATTERN_ROW_ID,
        canonical_name="mcp__<server>__<tool>",
        aliases=(),
        evidence_tier="official_mcp_documentation",
        recognized=True,
        normalized="not_applicable",
        classified=True,
        runtime_event_value=None,
        stream_support=True,
        non_stream_support=True,
        forward_or_consume="forwarded",
        control_api="not_applicable",
        persisted="when_orchestration_enabled",
        replayed="when_orchestration_enabled",
        policy_governed=True,
        tests=("unit:test_capability_registry", "unit:test_runtime_action_classifier"),
        implementation_status=BridgeImplementationStatus.IMPLEMENTED.value,
        residual_limitation=None,
    )


def build_all_coverage_rows() -> tuple[CoverageRow, ...]:
    reg = get_capability_registry()
    rows = tuple(row_for_record(r) for r in reg.records)
    return rows + (mcp_pattern_row(),)


def validate_test_manifest_matches_registry() -> None:
    reg = get_capability_registry()
    ids = {r.id for r in reg.records}
    manifest_ids = set(REQUIRED_TESTS_BY_CAPABILITY_ID.keys())
    if ids != manifest_ids:
        missing = ids - manifest_ids
        extra = manifest_ids - ids
        raise AssertionError(f"coverage manifest mismatch missing={missing!r} extra={extra!r}")


def export_coverage_json_bytes() -> bytes:
    reg = get_capability_registry()
    payload = {
        "registry_rows": [asdict(row_for_record(r)) for r in reg.records],
        "mcp_pattern": asdict(mcp_pattern_row()),
        "non_tool_families": [
            {
                "family_id": f.family_id,
                "status": f.status.value,
                "rationale": f.rationale,
            }
            for f in NON_TOOL_FAMILY_CLOSURE
        ],
    }
    return json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")


def write_coverage_artifact(path: Path) -> None:
    path.write_bytes(export_coverage_json_bytes())


def assert_mcp_pattern_consistency() -> None:
    assert is_mcp_style_tool_name("mcp__a__b")
    assert not is_mcp_style_tool_name("mcp__only")
