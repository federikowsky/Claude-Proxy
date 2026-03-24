"""Deterministic Bash command prefixes that indicate control-signal emulation (not exhaustive)."""

from __future__ import annotations

# Kept in one module so runtime_actions and the capability matrix stay aligned.
BASH_CONTROL_EMULATION_PREFIXES: tuple[str, ...] = (
    "echo done",
    "echo 'done'",
    'echo "done"',
    "echo complete",
    "echo finish",
    "exit 0",
    "exit 1",
)
