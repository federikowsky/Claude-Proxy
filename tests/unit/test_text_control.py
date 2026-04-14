from __future__ import annotations

import logging

import pytest

from llm_proxy.capabilities.enums import TextControlAttemptPolicy
from llm_proxy.capabilities.text_control import (
    apply_text_control_policy,
    detect_text_control_attempt,
)
from llm_proxy.domain.errors import TextControlAttemptBlockedError


@pytest.mark.parametrize(
    ("text", "expected_id"),
    [
        ("I approve", "i_approve"),
        ("  i approve.  ", "i_approve"),
        ("permission granted!", "permission_granted"),
        ("plan complete", "plan_complete"),
        ("done", "done"),
        ("not a control phrase", None),
        ("I approve things", None),
    ],
)
def test_detect_text_control_attempt(text: str, expected_id: str | None) -> None:
    assert detect_text_control_attempt(text) == expected_id


def test_apply_text_control_ignore() -> None:
    apply_text_control_policy(text="I approve", policy=TextControlAttemptPolicy.IGNORE)


def test_apply_text_control_warn_logs(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.WARNING, logger="llm_proxy.text_control")
    apply_text_control_policy(text="done", policy=TextControlAttemptPolicy.WARN)
    assert any("text_control_attempt" in r.message for r in caplog.records)


def test_apply_text_control_block() -> None:
    with pytest.raises(TextControlAttemptBlockedError) as ei:
        apply_text_control_policy(text="plan complete", policy=TextControlAttemptPolicy.BLOCK)
    assert ei.value.details.get("pattern_id") == "plan_complete"
    assert ei.value.error_type == "text_control_attempt_blocked"
