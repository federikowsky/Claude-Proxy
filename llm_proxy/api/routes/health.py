"""Health and readiness endpoint."""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

_logger = logging.getLogger("llm_proxy.health")

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    client_manager = request.app.state.client_manager

    provider_status: dict[str, str] = {}
    probe_tasks: dict[str, asyncio.Task[bool]] = {}

    for name, provider_cfg in settings.providers.items():
        if not provider_cfg.enabled:
            continue
        probe_tasks[name] = asyncio.create_task(
            _probe_provider(client_manager, provider_cfg.base_url)
        )

    if probe_tasks:
        results = await asyncio.gather(*probe_tasks.values(), return_exceptions=True)
        for name, result in zip(probe_tasks.keys(), results):
            if isinstance(result, Exception):
                provider_status[name] = "unreachable"
                _logger.warning("health probe failed for %s: %s", name, result)
            else:
                provider_status[name] = "reachable" if result else "unreachable"

    all_ok = all(s == "reachable" for s in provider_status.values()) if provider_status else True
    status_code = 200 if all_ok else 503

    return JSONResponse(
        content={
            "status": "ok" if all_ok else "degraded",
            "providers": provider_status,
        },
        status_code=status_code,
    )


async def _probe_provider(client_manager, base_url: str) -> bool:
    """Lightweight connectivity check --- any response means reachable."""
    try:
        client = await client_manager.get_client()
        await client.get(base_url, timeout=5.0)
        return True
    except Exception:
        return False
