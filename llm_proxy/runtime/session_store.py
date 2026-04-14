"""Runtime session snapshot store (pluggable)."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from llm_proxy.runtime.state import SessionRuntimeState


@runtime_checkable
class RuntimeSessionStore(Protocol):
    def get(self, session_id: str) -> SessionRuntimeState | None: ...

    def put(self, state: SessionRuntimeState) -> None: ...

    def delete(self, session_id: str) -> None: ...


class InMemoryRuntimeSessionStore:
    def __init__(self) -> None:
        self._data: dict[str, SessionRuntimeState] = {}

    def get(self, session_id: str) -> SessionRuntimeState | None:
        return self._data.get(session_id)

    def put(self, state: SessionRuntimeState) -> None:
        self._data[state.session_id] = state

    def delete(self, session_id: str) -> None:
        self._data.pop(session_id, None)

    def list_known_session_ids(self) -> list[str]:
        return sorted(self._data.keys())
