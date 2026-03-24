"""Runtime orchestration package (lazy exports avoid import cycles on submodule import)."""

from __future__ import annotations

from typing import Any

__all__ = [
    "InMemoryRuntimeSessionStore",
    "RuntimeOrchestrator",
]


def __getattr__(name: str) -> Any:
    if name == "RuntimeOrchestrator":
        from claude_proxy.runtime.orchestrator import RuntimeOrchestrator

        return RuntimeOrchestrator
    if name == "InMemoryRuntimeSessionStore":
        from claude_proxy.runtime.session_store import InMemoryRuntimeSessionStore

        return InMemoryRuntimeSessionStore
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
