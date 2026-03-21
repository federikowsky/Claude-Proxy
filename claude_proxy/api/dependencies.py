from __future__ import annotations

from fastapi import Request

from claude_proxy.application.services import MessageService


def get_message_service(request: Request) -> MessageService:
    return request.app.state.message_service

