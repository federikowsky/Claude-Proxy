from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from claude_proxy.infrastructure.config import load_settings
from claude_proxy.runtime.policies import (
    PermissionDeniedResolution,
    TimeoutResolution,
    UserMessageStartMode,
    UserRejectedResolution,
)
from claude_proxy.runtime.policy_binding import policies_from_settings
from tests.conftest import base_config


def test_policies_from_settings_reflect_yaml_values(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    cfg = base_config()
    cfg["bridge"]["runtime_policies"] = {
        "user_message_from_idle": "planning",
        "user_rejected": "aborted",
        "permission_denied": "planning",
        "tool_failed": "failed",
        "subtask_failed": "failed",
        "timeout_resolution": "interrupted",
        "plan_exit_target": "completing",
    }
    path = tmp_path / "cfg.yaml"
    with path.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, sort_keys=False)
    settings = load_settings(path)
    pol = policies_from_settings(settings.bridge.runtime_policies)
    assert pol.user_message_from_idle is UserMessageStartMode.PLANNING
    assert pol.user_rejected is UserRejectedResolution.ABORTED
    assert pol.permission_denied is PermissionDeniedResolution.PLANNING
    assert pol.timeout_resolution is TimeoutResolution.INTERRUPTED
