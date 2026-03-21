from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, Response, StreamingResponse

from claude_proxy.api.dependencies import get_message_service
from claude_proxy.api.schemas import AnthropicMessagesRequest
from claude_proxy.application.services import MessageService

router = APIRouter()


@router.post("/v1/messages")
async def messages(
    payload: AnthropicMessagesRequest,
    service: MessageService = Depends(get_message_service),
) -> Response:
    request = payload.to_domain()
    if request.stream:
        stream = await service.stream(request)
        return StreamingResponse(
            stream,
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    response = await service.complete(request)
    return JSONResponse(content=response)
