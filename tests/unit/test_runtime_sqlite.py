from __future__ import annotations

import dataclasses
from pathlib import Path

from claude_proxy.infrastructure.config import RuntimeOrchestrationPolicySettings
from claude_proxy.runtime.events import RuntimeEventKind
from claude_proxy.runtime.orchestrator import RuntimeOrchestrator
from claude_proxy.runtime.persistence.sqlite_backend import SqliteRuntimeStores
from claude_proxy.runtime.policy_binding import policies_from_settings
from claude_proxy.runtime.recovery import replay_persisted_session
from claude_proxy.runtime.state import RuntimeState
from claude_proxy.runtime.state_machine import idle_session


def test_sqlite_roundtrip_session_and_events(tmp_path: Path) -> None:
    path = tmp_path / "rt.db"
    sql = SqliteRuntimeStores(path)
    store, log = sql.session_store, sql.event_log
    s0 = idle_session("s1")
    s0 = dataclasses.replace(s0, state=RuntimeState.EXECUTING)
    store.put(s0)
    log.append("s1", RuntimeEventKind.USER_MESSAGE_RECEIVED, {})
    log.append("s1", RuntimeEventKind.MODEL_TEXT_EMITTED, {})
    sql.close()

    sql2 = SqliteRuntimeStores(path)
    try:
        assert sql2.session_store.get("s1") is not None
        assert sql2.session_store.get("s1").state is RuntimeState.EXECUTING
        evs = sql2.event_log.load_range("s1", 0)
        assert len(evs) == 2
        assert evs[0].seq == 0
        assert evs[1].kind is RuntimeEventKind.MODEL_TEXT_EMITTED
        assert "s1" in sql2.session_store.list_known_session_ids()
    finally:
        sql2.close()


def test_sqlite_replay_full_persists_store(tmp_path: Path) -> None:
    path = tmp_path / "r.db"
    sql = SqliteRuntimeStores(path)
    try:
        pol = policies_from_settings(RuntimeOrchestrationPolicySettings())
        orch = RuntimeOrchestrator(store=sql.session_store, log=sql.event_log, policies=pol)
        s = orch.load_or_idle("x")
        s, _ = orch.apply_input_event(s, RuntimeEventKind.USER_MESSAGE_RECEIVED, {})
        s, _ = orch.apply_input_event(
            s,
            RuntimeEventKind.MODEL_TOOL_CALL_PROPOSED,
            {"tool_use_id": "t1"},
        )
        replay_persisted_session(
            "x",
            log=sql.event_log,
            store=sql.session_store,
            policies=pol,
            mode="full",
        )
        st = sql.session_store.get("x")
        assert st is not None
        assert st.state is RuntimeState.EXECUTING_TOOL
    finally:
        sql.close()


def test_checkpoint_replay_tail(tmp_path: Path) -> None:
    path = tmp_path / "c.db"
    sql = SqliteRuntimeStores(path)
    try:
        pol = policies_from_settings(RuntimeOrchestrationPolicySettings())
        orch = RuntimeOrchestrator(store=sql.session_store, log=sql.event_log, policies=pol)
        s = orch.load_or_idle("z")
        s = orch.on_user_turn_start(s)
        s = orch.checkpoint(s)
        s, _ = orch.apply_input_event(s, RuntimeEventKind.MODEL_TEXT_EMITTED, {})
        ns = orch.replay_persisted("z", "from_checkpoint")
        assert ns.state is RuntimeState.EXECUTING
    finally:
        sql.close()
