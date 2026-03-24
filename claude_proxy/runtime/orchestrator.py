"""Session lifecycle: log append, state transitions, forward/consume decisions."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal

from claude_proxy.capabilities.enums import BridgeImplementationStatus
from claude_proxy.capabilities.registry import get_capability_registry
from claude_proxy.capabilities.signals import DEFAULT_TOOL_USE_SIGNAL_CONTEXT, ToolUseSignalContext
from claude_proxy.capabilities.tool_use_prepare import normalize_tool_use_for_runtime
from claude_proxy.domain.models import ContentBlockStartEvent, ToolUseBlock
from claude_proxy.runtime.classifier import RuntimeModelClassifier
from claude_proxy.runtime.errors import (
    CapabilityNotImplementedInBridgeError,
    InvalidModelRuntimeActionError,
    InvalidRuntimeTransitionError,
    RuntimeOrchestrationError,
)
from claude_proxy.runtime.event_log import RuntimeEventLog
from claude_proxy.runtime.events import RuntimeEvent, RuntimeEventKind
from claude_proxy.runtime.policies import RuntimeOrchestrationPolicies
from claude_proxy.runtime.session_store import RuntimeSessionStore
from claude_proxy.runtime.state import SessionRuntimeState
from claude_proxy.runtime.state_machine import apply_runtime_transition, idle_session


def effective_runtime_session_id(
    *,
    metadata: dict[str, Any] | None,
    header_session_id: str | None = None,
) -> str:
    import uuid

    md = metadata or {}
    sid = md.get("runtime_session_id")
    if isinstance(sid, str) and sid.strip():
        return sid.strip()
    if header_session_id and header_session_id.strip():
        return header_session_id.strip()
    return uuid.uuid4().hex


class RuntimeOrchestrator:
    """Owns runtime state via store + append-only event log."""

    def __init__(
        self,
        *,
        store: RuntimeSessionStore,
        log: RuntimeEventLog,
        policies: RuntimeOrchestrationPolicies | None = None,
        classifier: RuntimeModelClassifier | None = None,
    ) -> None:
        self._store = store
        self._log = log
        self._policies = policies or RuntimeOrchestrationPolicies()
        self._classifier = classifier or RuntimeModelClassifier()

    @property
    def policies(self) -> RuntimeOrchestrationPolicies:
        return self._policies

    def load_or_idle(self, session_id: str) -> SessionRuntimeState:
        s = self._store.get(session_id)
        return s if s is not None else idle_session(session_id)

    def persist(self, session: SessionRuntimeState) -> None:
        self._store.put(session)

    def apply_input_event(
        self,
        session: SessionRuntimeState,
        kind: RuntimeEventKind,
        payload: dict[str, Any],
        *,
        log_event: bool = True,
    ) -> tuple[SessionRuntimeState, tuple[tuple[RuntimeEventKind, dict[str, object]], ...]]:
        if log_event:
            self._log.append(session.session_id, kind, dict(payload))
        try:
            ns, internal = apply_runtime_transition(session, kind, payload, policies=self._policies)
        except InvalidRuntimeTransitionError:
            raise
        for ik, ip in internal:
            self._log.append(ns.session_id, ik, dict(ip))
        self._store.put(ns)
        return ns, internal

    def on_user_turn_start(
        self,
        session: SessionRuntimeState,
        *,
        payload: dict[str, Any] | None = None,
    ) -> SessionRuntimeState:
        ns, _ = self.apply_input_event(
            session,
            RuntimeEventKind.USER_MESSAGE_RECEIVED,
            payload or {},
        )
        return ns

    def on_model_text_block_started(self, session: SessionRuntimeState) -> SessionRuntimeState:
        ns, _ = self.apply_input_event(
            session,
            RuntimeEventKind.MODEL_TEXT_EMITTED,
            {},
        )
        return ns

    def process_tool_block_start(
        self,
        session: SessionRuntimeState,
        event: ContentBlockStartEvent,
        *,
        signal_context: ToolUseSignalContext | None = None,
    ) -> tuple[SessionRuntimeState, ContentBlockStartEvent | None]:
        if not isinstance(event.block, ToolUseBlock):
            raise RuntimeOrchestrationError("expected ToolUseBlock")
        base = signal_context or DEFAULT_TOOL_USE_SIGNAL_CONTEXT
        ctx = replace(base, session_state=session.state.value)
        rec = get_capability_registry().resolve(event.block.name)
        if rec is not None and rec.implementation_status is BridgeImplementationStatus.INVENTORY_ONLY:
            raise CapabilityNotImplementedInBridgeError(
                "capability is inventory-only in this bridge",
                details={"capability_id": rec.id, "tool": event.block.name},
            )
        normalized_block = normalize_tool_use_for_runtime(event.block, policies=self._policies)
        if normalized_block is not event.block:
            event = replace(event, block=normalized_block)
        mc = self._classifier.classify_tool_use(event.block, signal_context=ctx)
        ns, internal = self.apply_input_event(session, mc.event_kind, mc.payload)
        forward = any(ik is RuntimeEventKind.ACTION_FORWARDED for ik, _ in internal)
        if ns.state.value == "failed":
            raise RuntimeOrchestrationError(
                ns.failure_reason or "runtime_failed",
                details={"tool": event.block.name},
            )
        if mc.forward_ordinary_tool and forward:
            return ns, event
        if mc.event_kind is RuntimeEventKind.MODEL_INVALID_RUNTIME_ACTION:
            raise InvalidModelRuntimeActionError(
                str(mc.payload.get("reason", "invalid_runtime_action")),
                details={"tool": event.block.name},
            )
        return ns, None

    def log_upstream_turn_ended(self, session: SessionRuntimeState) -> None:
        self._log.append(
            session.session_id,
            RuntimeEventKind.STREAM_TERMINATED_BY_RUNTIME,
            {},
        )

    def log_stream_terminated(self, session: SessionRuntimeState) -> None:
        self.log_upstream_turn_ended(session)

    def checkpoint(self, session: SessionRuntimeState) -> SessionRuntimeState:
        from claude_proxy.runtime.recovery import append_checkpoint_event

        ns = replace_checkpoint_seq(session, session.checkpoint_seq + 1)
        append_checkpoint_event(self._log, ns)
        self._store.put(ns)
        return ns

    def list_known_session_ids(self) -> list[str]:
        ids: set[str] = set()
        if hasattr(self._store, "list_known_session_ids"):
            ids.update(self._store.list_known_session_ids())
        if hasattr(self._log, "list_session_ids"):
            ids.update(self._log.list_session_ids())
        return sorted(ids)

    def replay_persisted(self, session_id: str, mode: Literal["full", "from_checkpoint"]) -> SessionRuntimeState:
        from claude_proxy.runtime.recovery import replay_persisted_session

        return replay_persisted_session(
            session_id,
            log=self._log,
            store=self._store,
            policies=self._policies,
            mode=mode,
        )

    def load_event_slice(self, session_id: str, since_seq: int = 0, limit: int = 500) -> list[RuntimeEvent]:
        raw = list(self._log.load_range(session_id, since_seq))
        return raw[:limit]


def replace_checkpoint_seq(session: SessionRuntimeState, seq: int) -> SessionRuntimeState:
    from dataclasses import replace

    from claude_proxy.runtime.state import sync_modes_with_state

    s = replace(session, checkpoint_seq=seq)
    s.modes = sync_modes_with_state(s.state, s.modes)
    return s
