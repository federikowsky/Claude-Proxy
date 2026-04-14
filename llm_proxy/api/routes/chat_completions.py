"""OpenAI Chat Completions route.

POST /v1/chat/completions — accepts OpenAI-format requests, returns OpenAI-format responses.
The request is translated to canonical ChatRequest, processed through the same provider
pipeline, and egressed through the OpenAI encoder.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from llm_proxy.api.schemas_openai import OpenAIChatCompletionsRequest
from llm_proxy.application.services import MessageService
from llm_proxy.domain.models import ProviderRequestContext

router = APIRouter()


def _get_openai_service(request: Request) -> MessageService:
    return request.app.state.openai_message_service


@router.post("/v1/chat/completions")
async def chat_completions(
    payload: OpenAIChatCompletionsRequest,
    request: Request,
    service: MessageService = Depends(_get_openai_service),
) -> Response:
    domain_request = payload.to_domain()
    provider_context = ProviderRequestContext(
        headers=(),
        query_params=tuple(request.query_params.multi_items()),
    )

    if domain_request.stream:
        stream = await service.stream(domain_request, provider_context)
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    response = await service.complete(domain_request, provider_context)
    return JSONResponse(content=response)
