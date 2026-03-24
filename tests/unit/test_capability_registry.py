from __future__ import annotations

import pytest

from claude_proxy.capabilities.builtins import OFFICIAL_SDK_TOOL_CANONICALS, builtin_capability_records
from claude_proxy.capabilities.enums import CapabilityInventoryClass, SchemaContractKind
from claude_proxy.capabilities.registry import CapabilityRegistry, get_capability_registry, is_mcp_style_tool_name
from claude_proxy.domain.enums import ToolCategory


def test_registry_singleton_builds_without_alias_collision() -> None:
    reg = CapabilityRegistry(builtin_capability_records())
    assert len(reg.records) >= 1


def test_get_capability_registry_is_cached() -> None:
    assert get_capability_registry() is get_capability_registry()


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("AskUserQuestion", ToolCategory.STATE_CONTROL),
        ("ask_user", ToolCategory.STATE_CONTROL),
        ("mcp__myserver__search", ToolCategory.MCP),
        ("bash", ToolCategory.GENERIC),
        ("Task", ToolCategory.ORCHESTRATION),
        ("Agent", ToolCategory.ORCHESTRATION),
        ("TodoRead", ToolCategory.GENERIC),
        ("unknown_custom_xyz", ToolCategory.ORDINARY),
    ],
)
def test_classify_tool_category(name: str, expected: ToolCategory) -> None:
    assert get_capability_registry().classify_tool_category(name) is expected


def test_mcp_naming_allows_multi_segment_tool() -> None:
    assert is_mcp_style_tool_name("mcp__srv__tool__nested")


def test_triggers_abort_for_abort_alias() -> None:
    reg = get_capability_registry()
    assert reg.triggers_abort("abort")
    assert reg.triggers_abort("kill_session")


def test_todo_write_signal() -> None:
    assert get_capability_registry().todo_write_text_signal("TodoWrite")


def test_official_sdk_canonicals_present_in_registry() -> None:
    canon = {r.canonical_name for r in get_capability_registry().records}
    missing = OFFICIAL_SDK_TOOL_CANONICALS - canon
    assert not missing, f"missing official canonicals: {missing}"


def test_interactive_contract_on_ask_user_question() -> None:
    reg = get_capability_registry()
    rec = reg.resolve("AskUserQuestion")
    assert rec is not None
    assert rec.schema_contract is SchemaContractKind.INTERACTIVE_QUESTION


def test_inventory_class_coverage_minimum() -> None:
    reg = get_capability_registry()
    classes = {r.inventory_class for r in reg.records}
    assert CapabilityInventoryClass.BUILTIN_ORDINARY in classes
    assert CapabilityInventoryClass.INTERACTIVE_USER_DECISION in classes
    assert CapabilityInventoryClass.SUBAGENT_ORCHESTRATION in classes


def test_coverage_test_manifest_matches_registry_ids() -> None:
    from claude_proxy.capabilities.coverage_matrix import validate_test_manifest_matches_registry

    validate_test_manifest_matches_registry()


def test_exported_coverage_json_registry_ids_match_singleton() -> None:
    import json

    from claude_proxy.capabilities.coverage_matrix import export_coverage_json_bytes

    payload = json.loads(export_coverage_json_bytes().decode())
    reg_ids = {r.id for r in get_capability_registry().records}
    row_ids = {r["capability_id"] for r in payload["registry_rows"]}
    assert row_ids == reg_ids
    assert payload["mcp_pattern"]["capability_id"] == "mcp__dynamic_pattern"
    assert {f["family_id"] for f in payload["non_tool_families"]} == {
        "hooks",
        "runtime_system_messages",
        "worktree",
        "remote",
        "teammate",
        "background_task_progress",
    }
