from __future__ import annotations

from fastapi import Request

from llm_proxy.application.services import MessageService
from llm_proxy.runtime.errors import RuntimeOrchestrationDisabledError
from llm_proxy.runtime.orchestrator import RuntimeOrchestrator


def get_message_service(request: Request) -> MessageService:
    return request.app.state.message_service


def get_runtime_orchestrator(request: Request) -> RuntimeOrchestrator:
    orch = getattr(request.app.state, "runtime_orchestrator", None)
    if orch is None:
        raise RuntimeOrchestrationDisabledError(
            "runtime orchestration is disabled",
            details={},
        )
    return orch

