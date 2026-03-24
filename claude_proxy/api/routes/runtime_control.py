"""External control plane for runtime orchestration (sessions, approvals, recovery)."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from claude_proxy.api.dependencies import get_runtime_orchestrator
from claude_proxy.runtime.events import RuntimeEventKind
from claude_proxy.runtime.orchestrator import RuntimeOrchestrator
from claude_proxy.runtime.session_codec import session_to_dict

router = APIRouter(prefix="/v1/runtime", tags=["runtime"])


class ReasonBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = ""


class SubtaskIdBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    subtask_id: str = ""


class ToolUseIdBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_use_id: str = Field(..., min_length=1)


class ReplayBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["full", "from_checkpoint"]


class RuntimeEventOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    seq: int
    kind: str
    payload: dict[str, Any]


def _apply(
    orch: RuntimeOrchestrator,
    session_id: str,
    kind: RuntimeEventKind,
    payload: dict[str, Any],
) -> dict[str, Any]:
    session = orch.load_or_idle(session_id)
    ns, _ = orch.apply_input_event(session, kind, payload)
    return session_to_dict(ns)


@router.post("/sessions/{session_id}/user-turn")
async def user_turn(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    """Apply USER_MESSAGE_RECEIVED (e.g. when the user turn is committed outside /v1/messages)."""
    return {"session": _apply(orch, session_id, RuntimeEventKind.USER_MESSAGE_RECEIVED, {})}


@router.get("/sessions")
async def list_sessions(orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator)) -> dict[str, list[str]]:
    return {"session_ids": orch.list_known_session_ids()}


@router.get("/sessions/{session_id}")
async def get_session_status(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    s = orch.load_or_idle(session_id)
    return {"session": session_to_dict(s)}


@router.get("/sessions/{session_id}/events")
async def get_session_events(
    session_id: str,
    since_seq: int = 0,
    limit: int = Query(default=500, ge=1, le=10_000),
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, list[RuntimeEventOut]]:
    sliced = orch.load_event_slice(session_id, since_seq=since_seq, limit=limit)
    return {
        "events": [
            RuntimeEventOut(seq=e.seq, kind=e.kind.value, payload=dict(e.payload)) for e in sliced
        ],
    }


@router.post("/sessions/{session_id}/approve")
async def approve(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.USER_APPROVED, {})}


@router.post("/sessions/{session_id}/reject")
async def reject(
    session_id: str,
    body: ReasonBody | None = None,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body and body.reason:
        payload["reason"] = body.reason
    return {"session": _apply(orch, session_id, RuntimeEventKind.USER_REJECTED, payload)}


@router.post("/sessions/{session_id}/permission/grant")
async def permission_grant(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.USER_PERMISSION_GRANTED, {})}


@router.post("/sessions/{session_id}/permission/deny")
async def permission_deny(
    session_id: str,
    body: ReasonBody | None = None,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body and body.reason:
        payload["reason"] = body.reason
    return {"session": _apply(orch, session_id, RuntimeEventKind.USER_PERMISSION_DENIED, payload)}


@router.post("/sessions/{session_id}/subtask/started")
async def subtask_started(
    session_id: str,
    body: SubtaskIdBody | None = None,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body and body.subtask_id:
        payload["subtask_id"] = body.subtask_id
    return {"session": _apply(orch, session_id, RuntimeEventKind.SUBTASK_STARTED, payload)}


@router.post("/sessions/{session_id}/subtask/completed")
async def subtask_completed(
    session_id: str,
    body: SubtaskIdBody | None = None,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if body and body.subtask_id:
        payload["subtask_id"] = body.subtask_id
    return {"session": _apply(orch, session_id, RuntimeEventKind.SUBTASK_COMPLETED, payload)}


@router.post("/sessions/{session_id}/subtask/failed")
async def subtask_failed(
    session_id: str,
    body: ReasonBody | None = None,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    payload: dict[str, Any] = {"reason": body.reason if body else "subtask_failed"}
    return {"session": _apply(orch, session_id, RuntimeEventKind.SUBTASK_FAILED, payload)}


@router.post("/sessions/{session_id}/tool-execution/started")
async def tool_execution_started(
    session_id: str,
    body: ToolUseIdBody,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {
        "session": _apply(
            orch,
            session_id,
            RuntimeEventKind.TOOL_EXECUTION_STARTED,
            {"tool_use_id": body.tool_use_id},
        ),
    }


@router.post("/sessions/{session_id}/tool-execution/succeeded")
async def tool_execution_succeeded(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED, {})}


@router.post("/sessions/{session_id}/tool-execution/failed")
async def tool_execution_failed(
    session_id: str,
    body: ReasonBody | None = None,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    payload: dict[str, Any] = {"reason": body.reason if body else "tool_failed"}
    return {"session": _apply(orch, session_id, RuntimeEventKind.TOOL_EXECUTION_FAILED, payload)}


@router.post("/sessions/{session_id}/finalize/success")
async def finalize_success(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {
        "session": _apply(
            orch,
            session_id,
            RuntimeEventKind.TOOL_EXECUTION_SUCCEEDED,
            {"finalize": True},
        ),
    }


@router.post("/sessions/{session_id}/finalize/failure")
async def finalize_failure(
    session_id: str,
    body: ReasonBody | None = None,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    payload: dict[str, Any] = {"finalize": True, "reason": body.reason if body else "finalization_failed"}
    return {"session": _apply(orch, session_id, RuntimeEventKind.TOOL_EXECUTION_FAILED, payload)}


@router.post("/sessions/{session_id}/pause")
async def pause(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.SESSION_PAUSE_REQUESTED, {})}


@router.post("/sessions/{session_id}/resume")
async def resume(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.SESSION_RESUME_REQUESTED, {})}


@router.post("/sessions/{session_id}/abort")
async def abort(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.SESSION_ABORT_REQUESTED, {})}


@router.post("/sessions/{session_id}/interrupt")
async def interrupt(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.STREAM_INTERRUPTED, {})}


@router.post("/sessions/{session_id}/timeout")
async def timeout(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.TIMEOUT_OCCURRED, {})}


@router.post("/sessions/{session_id}/recovery/request")
async def recovery_request(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    return {"session": _apply(orch, session_id, RuntimeEventKind.RECOVERY_REQUESTED, {})}


@router.post("/sessions/{session_id}/recovery/replay")
async def recovery_replay(
    session_id: str,
    body: ReplayBody,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    ns = orch.replay_persisted(session_id, body.mode)
    return {"session": session_to_dict(ns)}


@router.post("/sessions/{session_id}/checkpoint")
async def checkpoint(
    session_id: str,
    orch: RuntimeOrchestrator = Depends(get_runtime_orchestrator),
) -> dict[str, Any]:
    s = orch.load_or_idle(session_id)
    ns = orch.checkpoint(s)
    return {"session": session_to_dict(ns)}
