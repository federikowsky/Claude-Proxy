from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from claude_proxy.api.errors import install_error_handlers
from claude_proxy.api.routes.health import router as health_router
from claude_proxy.api.routes.messages import router as messages_router
from claude_proxy.application.policies import AnthropicSafeStreamNormalizer
from claude_proxy.application.services import MessageService
from claude_proxy.application.sse import AnthropicSseEncoder
from claude_proxy.infrastructure.config import Settings, load_settings
from claude_proxy.infrastructure.http import SharedAsyncClientManager
from claude_proxy.infrastructure.logging import setup_logging
from claude_proxy.infrastructure.providers import build_provider_registry
from claude_proxy.infrastructure.resolvers import StaticModelResolver


def create_app(
    settings: Settings | None = None,
    *,
    transport=None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    setup_logging(resolved_settings.server.log_level)
    client_manager = SharedAsyncClientManager(resolved_settings, transport=transport)
    resolver = StaticModelResolver(resolved_settings)
    normalizer = AnthropicSafeStreamNormalizer(
        emit_usage=resolved_settings.stream.emit_usage,
        max_reasoning_buffer_chars=resolved_settings.stream.max_reasoning_buffer_chars,
    )
    encoder = AnthropicSseEncoder()
    providers = build_provider_registry(resolved_settings, client_manager)
    message_service = MessageService(
        resolver=resolver,
        providers=providers,
        normalizer=normalizer,
        encoder=encoder,
        stream_policy=resolved_settings.stream.policy,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        try:
            yield
        finally:
            await client_manager.close()

    app = FastAPI(title="claude-proxy", version="0.1.0", lifespan=lifespan)

    app.state.settings = resolved_settings
    app.state.client_manager = client_manager
    app.state.message_service = message_service

    app.include_router(health_router)
    app.include_router(messages_router)
    install_error_handlers(app)

    return app


app = create_app()
