from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from llm_proxy.api.dependencies import get_message_service
from llm_proxy.api.schemas import AnthropicCountTokensRequest, AnthropicMessagesRequest
from llm_proxy.application.services import MessageService
from llm_proxy.domain.models import ProviderRequestContext

router = APIRouter()


def _provider_request_context(request: Request) -> ProviderRequestContext:
    headers: list[tuple[str, str]] = []
    beta_values = request.headers.getlist("anthropic-beta")
    if beta_values:
        headers.append(("anthropic-beta", ",".join(beta_values)))
    version = request.headers.get("anthropic-version")
    if version:
        headers.append(("anthropic-version", version))
    return ProviderRequestContext(
        headers=tuple(headers),
        query_params=tuple(request.query_params.multi_items()),
    )


@router.post("/v1/messages")
async def messages(
    payload: AnthropicMessagesRequest,
    request: Request,
    service: MessageService = Depends(get_message_service),
) -> Response:
    domain_request = payload.to_domain()
    provider_context = _provider_request_context(request)
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


@router.post("/v1/messages/count_tokens")
async def count_tokens(
    payload: AnthropicCountTokensRequest,
    request: Request,
    service: MessageService = Depends(get_message_service),
) -> JSONResponse:
    response = await service.count_tokens(
        payload.to_domain(),
        _provider_request_context(request),
    )
    return JSONResponse(content=response)
