"""Authoritative runtime session state and mode qualifiers."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class RuntimeState(StrEnum):
    """Top-level runtime states owned by the proxy."""

    IDLE = "idle"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    AWAITING_PERMISSION = "awaiting_permission"
    EXECUTING = "executing"
    EXECUTING_TOOL = "executing_tool"
    ORCHESTRATING = "orchestrating"
    AWAITING_SUBTASK = "awaiting_subtask"
    PAUSED = "paused"
    COMPLETING = "completing"
    COMPLETED = "completed"
    FAILED = "failed"
    ABORTED = "aborted"
    INTERRUPTED = "interrupted"
    RECOVERING = "recovering"


class PlanMode(StrEnum):
    OFF = "off"
    ACTIVE = "active"


class ApprovalMode(StrEnum):
    OFF = "off"
    REQUIRED = "required"


class PermissionMode(StrEnum):
    OFF = "off"
    REQUIRED = "required"


class ExecutionMode(StrEnum):
    IDLE = "idle"
    ACTIVE = "active"
    TOOL_IN_FLIGHT = "tool_in_flight"


class DelegationMode(StrEnum):
    OFF = "off"
    ACTIVE = "active"
    AWAITING_CHILD = "awaiting_child"


class CompletionMode(StrEnum):
    OFF = "off"
    IN_PROGRESS = "in_progress"
    COMMITTED = "committed"


@dataclass(slots=True)
class ModeQualifiers:
    plan_mode: PlanMode = PlanMode.OFF
    approval_mode: ApprovalMode = ApprovalMode.OFF
    permission_mode: PermissionMode = PermissionMode.OFF
    execution_mode: ExecutionMode = ExecutionMode.IDLE
    delegation_mode: DelegationMode = DelegationMode.OFF
    completion_mode: CompletionMode = CompletionMode.OFF


_TERMINAL: frozenset[RuntimeState] = frozenset(
    {
        RuntimeState.COMPLETED,
        RuntimeState.FAILED,
        RuntimeState.ABORTED,
    }
)


def sync_modes_with_state(state: RuntimeState, modes: ModeQualifiers) -> ModeQualifiers:
    """Derive mode flags from state (single source of truth: state drives modes)."""
    del modes  # explicit state-derived view; callers pass placeholder
    if state in _TERMINAL:
        return ModeQualifiers(
            completion_mode=CompletionMode.COMMITTED if state is RuntimeState.COMPLETED else CompletionMode.OFF,
        )
    return ModeQualifiers(
        plan_mode=PlanMode.ACTIVE if state is RuntimeState.PLANNING else PlanMode.OFF,
        approval_mode=ApprovalMode.REQUIRED if state is RuntimeState.AWAITING_APPROVAL else ApprovalMode.OFF,
        permission_mode=PermissionMode.REQUIRED if state is RuntimeState.AWAITING_PERMISSION else PermissionMode.OFF,
        execution_mode=ExecutionMode.TOOL_IN_FLIGHT
        if state is RuntimeState.EXECUTING_TOOL
        else ExecutionMode.ACTIVE
        if state
        in (
            RuntimeState.EXECUTING,
            RuntimeState.COMPLETING,
        )
        else ExecutionMode.IDLE,
        delegation_mode=DelegationMode.AWAITING_CHILD
        if state is RuntimeState.AWAITING_SUBTASK
        else DelegationMode.ACTIVE
        if state in (RuntimeState.ORCHESTRATING, RuntimeState.AWAITING_SUBTASK)
        else DelegationMode.OFF,
        completion_mode=CompletionMode.IN_PROGRESS
        if state is RuntimeState.COMPLETING
        else CompletionMode.OFF,
    )


@dataclass(slots=True)
class PendingApproval:
    """Opaque handle for approval gating (serialized in checkpoint)."""

    approval_id: str
    resume_state: RuntimeState
    tool_name: str = ""
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class PendingPermission:
    permission_id: str
    resume_state: RuntimeState
    tool_name: str = ""
    payload: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class SessionRuntimeState:
    """Persisted orchestration snapshot for one session."""

    session_id: str
    state: RuntimeState
    modes: ModeQualifiers
    pending_approval: PendingApproval | None
    pending_permission: PendingPermission | None
    in_flight_tool_id: str | None
    unresolved_subtasks: int
    subtask_ids: tuple[str, ...]
    paused_resume_state: RuntimeState | None
    last_committed_turn_seq: int
    checkpoint_seq: int
    failure_reason: str | None = None

    def __post_init__(self) -> None:
        self.modes = sync_modes_with_state(self.state, self.modes)
