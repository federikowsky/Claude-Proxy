"""Multi-signal classification context (registry remains authoritative for identity)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class ToolUseSignalContext:
    """Non-name signals applied after registry resolution (deterministic, loggable)."""

    delivery: Literal["stream", "non_stream"]
    origin: Literal["model_tool_use", "control_api", "replay_reapply"]
    session_state: str | None = None


DEFAULT_TOOL_USE_SIGNAL_CONTEXT = ToolUseSignalContext(
    delivery="non_stream",
    origin="model_tool_use",
    session_state=None,
)
