from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from llm_proxy.api.errors import install_error_handlers
from llm_proxy.api.http_debug import install_http_debug_middleware
from llm_proxy.api.middleware import RequestLoggingMiddleware
from llm_proxy.api.routes.health import router as health_router
from llm_proxy.api.routes.models import router as models_router
from llm_proxy.api.routes.messages import router as messages_router
from llm_proxy.api.routes.chat_completions import router as chat_completions_router
from llm_proxy.api.routes.runtime_control import router as runtime_control_router
from llm_proxy.application.policies import CompatibilityNormalizer, StreamEventSequencer
from llm_proxy.application.request_preparer import ModelAwareRequestPreparer
from llm_proxy.application.services import MessageService
from llm_proxy.application.openai_egress import OpenAIResponseEncoder, OpenAISseEncoder
from llm_proxy.application.sse import AnthropicResponseEncoder, AnthropicSseEncoder
from llm_proxy.infrastructure.config import Settings, load_settings
from llm_proxy.infrastructure.http import SharedAsyncClientManager
from llm_proxy.infrastructure.logging import setup_logging
from llm_proxy.infrastructure.providers import build_provider_registry
from llm_proxy.infrastructure.resolvers import StaticModelResolver
from llm_proxy.runtime.event_log import InMemoryRuntimeEventLog
from llm_proxy.runtime.orchestrator import RuntimeOrchestrator
from llm_proxy.runtime.persistence.sqlite_backend import SqliteRuntimeStores
from llm_proxy.runtime.policy_binding import policies_from_settings
from llm_proxy.runtime.session_store import InMemoryRuntimeSessionStore


def create_app(
    settings: Settings | None = None,
    *,
    transport=None,
) -> FastAPI:
    resolved_settings = settings or load_settings()
    setup_logging(resolved_settings.server.log_level)
    client_manager = SharedAsyncClientManager(resolved_settings, transport=transport)
    resolver = StaticModelResolver(resolved_settings)
    request_preparer = ModelAwareRequestPreparer(
        allowed_request_fields=resolved_settings.bridge.passthrough_request_fields,
    )
    normalizer = CompatibilityNormalizer()
    sequencer = StreamEventSequencer()
    sse_encoder = AnthropicSseEncoder()
    response_encoder = AnthropicResponseEncoder()
    providers = build_provider_registry(resolved_settings, client_manager)
    runtime_orchestrator = None
    runtime_sqlite: SqliteRuntimeStores | None = None
    repair_policies = policies_from_settings(resolved_settings.bridge.runtime_policies)
    if resolved_settings.bridge.runtime_orchestration_enabled:
        if resolved_settings.bridge.runtime_persistence.backend == "sqlite":
            runtime_sqlite = SqliteRuntimeStores(resolved_settings.bridge.runtime_persistence.sqlite_path)
            runtime_orchestrator = RuntimeOrchestrator(
                store=runtime_sqlite.session_store,
                log=runtime_sqlite.event_log,
                policies=repair_policies,
            )
        else:
            runtime_orchestrator = RuntimeOrchestrator(
                store=InMemoryRuntimeSessionStore(),
                log=InMemoryRuntimeEventLog(),
                policies=repair_policies,
            )
    message_service = MessageService(
        resolver=resolver,
        providers=providers,
        request_preparer=request_preparer,
        normalizer=normalizer,
        sequencer=sequencer,
        sse_encoder=sse_encoder,
        response_encoder=response_encoder,
        compatibility_mode=resolved_settings.bridge.compatibility_mode,
        runtime_orchestrator=runtime_orchestrator,
        outbound_repair_policies=repair_policies,
        fallback_model=resolved_settings.routing.fallback_model,
        provider_settings=resolved_settings.providers,
        debug=resolved_settings.server.debug,
    )
    openai_message_service = MessageService(
        resolver=resolver,
        providers=providers,
        request_preparer=request_preparer,
        normalizer=normalizer,
        sequencer=StreamEventSequencer(),
        sse_encoder=OpenAISseEncoder(),
        response_encoder=OpenAIResponseEncoder(),
        compatibility_mode=resolved_settings.bridge.compatibility_mode,
        runtime_orchestrator=runtime_orchestrator,
        outbound_repair_policies=repair_policies,
        fallback_model=resolved_settings.routing.fallback_model,
        provider_settings=resolved_settings.providers,
        debug=resolved_settings.server.debug,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        try:
            yield
        finally:
            sql = getattr(app.state, "runtime_sqlite", None)
            if sql is not None:
                sql.close()
            await client_manager.close()

    app = FastAPI(title="llm-proxy", version="1.0.0", lifespan=lifespan)
    if resolved_settings.server.cors.enabled:
        cors = resolved_settings.server.cors
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(cors.allowed_origins),
            allow_methods=list(cors.allowed_methods),
            allow_headers=list(cors.allowed_headers),
            allow_credentials=cors.allow_credentials,
        )
    app.state.settings = resolved_settings
    app.state.client_manager = client_manager
    app.state.message_service = message_service
    app.state.openai_message_service = openai_message_service
    app.state.runtime_orchestrator = runtime_orchestrator
    app.state.runtime_sqlite = runtime_sqlite
    app.include_router(health_router)
    app.include_router(models_router)
    app.include_router(messages_router)
    app.include_router(chat_completions_router)
    app.include_router(runtime_control_router)
    install_error_handlers(app)
    install_http_debug_middleware(app)
    app.add_middleware(RequestLoggingMiddleware)
    return app


app = create_app()
