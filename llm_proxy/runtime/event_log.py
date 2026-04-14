"""Append-only runtime event log (pluggable persistence)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from llm_proxy.runtime.events import RuntimeEvent, RuntimeEventKind


@runtime_checkable
class RuntimeEventLog(Protocol):
    def append(self, session_id: str, kind: RuntimeEventKind, payload: dict[str, object]) -> RuntimeEvent:
        """Persist one event; returns record with assigned monotonic seq."""

    def load_range(self, session_id: str, start_seq: int = 0) -> Sequence[RuntimeEvent]:
        """Events with seq >= start_seq in order."""


class InMemoryRuntimeEventLog:
    def __init__(self) -> None:
        self._by_session: dict[str, list[RuntimeEvent]] = {}
        self._next_seq: dict[str, int] = {}

    def append(self, session_id: str, kind: RuntimeEventKind, payload: dict[str, object]) -> RuntimeEvent:
        seq = self._next_seq.get(session_id, 0)
        self._next_seq[session_id] = seq + 1
        record = RuntimeEvent(seq=seq, kind=kind, payload=dict(payload))
        self._by_session.setdefault(session_id, []).append(record)
        return record

    def load_range(self, session_id: str, start_seq: int = 0) -> Sequence[RuntimeEvent]:
        return [e for e in self._by_session.get(session_id, ()) if e.seq >= start_seq]

    def clone_log(self, session_id: str) -> list[RuntimeEvent]:
        return list(self._by_session.get(session_id, ()))

    def list_session_ids(self) -> list[str]:
        return sorted(self._by_session.keys())
