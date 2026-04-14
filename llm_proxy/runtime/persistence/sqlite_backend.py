"""SQLite-backed session store and append-only event log (WAL, transactional)."""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Sequence
from pathlib import Path

from llm_proxy.jsonutil import json_dumps, json_loads
from llm_proxy.runtime.events import RuntimeEvent, RuntimeEventKind
from llm_proxy.runtime.session_codec import session_from_dict, session_to_dict
from llm_proxy.runtime.state import SessionRuntimeState


def _dumps(data: object) -> str:
    return json_dumps(data).decode("utf-8")


_SCHEMA = """
CREATE TABLE IF NOT EXISTS runtime_schema (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  version INTEGER NOT NULL
);
INSERT OR IGNORE INTO runtime_schema (id, version) VALUES (1, 1);

CREATE TABLE IF NOT EXISTS runtime_sessions (
  session_id TEXT PRIMARY KEY NOT NULL,
  state_json TEXT NOT NULL,
  updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS runtime_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  seq INTEGER NOT NULL,
  kind TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at REAL NOT NULL,
  UNIQUE(session_id, seq)
);
CREATE INDEX IF NOT EXISTS idx_runtime_events_session_seq
  ON runtime_events(session_id, seq);
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
"""


class SqliteRuntimeStores:
    """Single SQLite file: session snapshots + append-only events (thread-safe)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @property
    def session_store(self) -> SqliteRuntimeSessionStore:
        return SqliteRuntimeSessionStore(self)

    @property
    def event_log(self) -> SqliteRuntimeEventLog:
        return SqliteRuntimeEventLog(self)


class SqliteRuntimeSessionStore:
    def __init__(self, backend: SqliteRuntimeStores) -> None:
        self._b = backend

    def get(self, session_id: str) -> SessionRuntimeState | None:
        with self._b._lock:
            row = self._b._conn.execute(
                "SELECT state_json FROM runtime_sessions WHERE session_id = ?",
                (session_id,),
            ).fetchone()
        if row is None:
            return None
        return session_from_dict(json_loads(row["state_json"]))

    def put(self, state: SessionRuntimeState) -> None:
        payload = _dumps(session_to_dict(state))
        now = time.time()
        with self._b._lock:
            self._b._conn.execute(
                """
                INSERT INTO runtime_sessions (session_id, state_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                  state_json = excluded.state_json,
                  updated_at = excluded.updated_at
                """,
                (state.session_id, payload, now),
            )
            self._b._conn.commit()

    def delete(self, session_id: str) -> None:
        with self._b._lock:
            self._b._conn.execute("DELETE FROM runtime_sessions WHERE session_id = ?", (session_id,))
            self._b._conn.commit()

    def list_known_session_ids(self) -> list[str]:
        with self._b._lock:
            a = {
                r[0]
                for r in self._b._conn.execute("SELECT session_id FROM runtime_sessions").fetchall()
            }
            b = {
                r[0]
                for r in self._b._conn.execute("SELECT DISTINCT session_id FROM runtime_events").fetchall()
            }
        return sorted(a | b)


class SqliteRuntimeEventLog:
    def __init__(self, backend: SqliteRuntimeStores) -> None:
        self._b = backend

    def append(self, session_id: str, kind: RuntimeEventKind, payload: dict[str, object]) -> RuntimeEvent:
        now = time.time()
        pj = _dumps(dict(payload))
        with self._b._lock:
            self._b._conn.execute("BEGIN IMMEDIATE")
            cur = self._b._conn.execute(
                "SELECT COALESCE(MAX(seq), -1) AS m FROM runtime_events WHERE session_id = ?",
                (session_id,),
            )
            row = cur.fetchone()
            seq = int(row["m"]) + 1
            self._b._conn.execute(
                """
                INSERT INTO runtime_events (session_id, seq, kind, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, seq, kind.value, pj, now),
            )
            self._b._conn.commit()
        return RuntimeEvent(seq=seq, kind=kind, payload=dict(payload))

    def load_range(self, session_id: str, start_seq: int = 0) -> Sequence[RuntimeEvent]:
        with self._b._lock:
            rows = self._b._conn.execute(
                """
                SELECT seq, kind, payload_json FROM runtime_events
                WHERE session_id = ? AND seq >= ?
                ORDER BY seq ASC
                """,
                (session_id, start_seq),
            ).fetchall()
        out: list[RuntimeEvent] = []
        for row in rows:
            kind = RuntimeEventKind(str(row["kind"]))
            payload = json_loads(row["payload_json"])
            if not isinstance(payload, dict):
                payload = {}
            out.append(RuntimeEvent(seq=int(row["seq"]), kind=kind, payload=payload))
        return out
