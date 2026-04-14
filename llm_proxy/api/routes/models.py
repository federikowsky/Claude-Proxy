"""OpenAI-compatible model listing endpoint."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


@router.get("/v1/models")
async def list_models(request: Request) -> JSONResponse:
    settings = request.app.state.settings
    models = []
    for model_name, model_config in sorted(settings.models.items()):
        if not model_config.enabled:
            continue
        models.append(
            {
                "id": model_name,
                "object": "model",
                "created": 0,
                "owned_by": model_config.provider,
                "permission": [],
                "root": model_name,
                "parent": None,
            }
        )
    return JSONResponse(content={"object": "list", "data": models})
