"""Plain-text phrases that resemble runtime control (never drive the state machine)."""

from __future__ import annotations

import json
import logging

from claude_proxy.capabilities.enums import TextControlAttemptPolicy

_logger = logging.getLogger("claude_proxy.text_control")

# After lower-case + whitespace collapse + trailing punctuation strip.
_CONTROL_PHRASE_CORES: frozenset[str] = frozenset(
    {
        "i approve",
        "permission granted",
        "plan complete",
        "done",
    },
)


def detect_text_control_attempt(text: str) -> str | None:
    """Return a stable phrase id if the whole block is control-like, else ``None``."""
    core = " ".join(text.strip().lower().split())
    core = core.rstrip(".!?").strip()
    if not core:
        return None
    if core not in _CONTROL_PHRASE_CORES:
        return None
    return core.replace(" ", "_")


def apply_text_control_policy(*, text: str, policy: TextControlAttemptPolicy) -> None:
    """Log and/or block; never mutates runtime state."""
    pid = detect_text_control_attempt(text)
    if pid is None:
        return
    payload = {
        "event": "text_control_attempt",
        "pattern_id": pid,
        "policy": policy.value,
        "text_preview": text.strip()[:200],
    }
    if policy is TextControlAttemptPolicy.IGNORE:
        return
    line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False)
    if policy is TextControlAttemptPolicy.WARN:
        _logger.warning("%s", line, extra={"extra_fields": payload})
        return
    from claude_proxy.domain.errors import TextControlAttemptBlockedError

    raise TextControlAttemptBlockedError(
        "model text resembles runtime control language; use tools or control API",
        details=payload,
    )
