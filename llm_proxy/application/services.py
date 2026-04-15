from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Mapping
from dataclasses import replace

from llm_proxy.application.runtime_contract import RuntimeContractEnforcer
from llm_proxy.domain.enums import CompatibilityMode
from llm_proxy.domain.errors import (
    ProviderHttpError,
    RoutingError,
    RuntimeContractError,
    SemanticLoopDetectedError,
    UpstreamTimeoutError,
)
from llm_proxy.domain.models import (
    CanonicalEvent,
    ChatRequest,
    ContentBlockStartEvent,
    ModelInfo,
    ProviderRequestContext,
    TextBlock,
    ToolUseBlock,
)
from llm_proxy.capabilities.text_control import apply_text_control_policy
from llm_proxy.capabilities.tool_use_prepare import (
    repair_chat_response_tool_blocks,
    repair_stream_tool_blocks,
)
from llm_proxy.runtime.errors import RuntimeOrchestrationError
from llm_proxy.runtime.policies import RuntimeOrchestrationPolicies
from llm_proxy.runtime.orchestrator import RuntimeOrchestrator, effective_runtime_session_id
from llm_proxy.runtime.stream import runtime_orchestrate_stream
from llm_proxy.infrastructure.config import ProviderSettings
from llm_proxy.infrastructure.retry import with_retry
from llm_proxy.domain.ports import (
    ModelProvider,
    ModelResolver,
    RequestPreparer,
    ResponseEncoder,
    ResponseNormalizer,
    SseEncoder,
)

_logger = logging.getLogger("llm_proxy.stream")
_SEMANTIC_LOOP_THRESHOLD = 3


class _SemanticLoopTracker:
    def __init__(self, threshold: int = _SEMANTIC_LOOP_THRESHOLD) -> None:
        self._threshold = threshold
        self._seen: dict[tuple[str, str], tuple[str, int]] = {}

    def observe(self, *, session_id: str, model_name: str, signature: str | None) -> None:
        key = (session_id, model_name)
        if signature is None:
            self._seen.pop(key, None)
            return
        prev = self._seen.get(key)
        count = prev[1] + 1 if prev is not None and prev[0] == signature else 1
        if count >= self._threshold:
            self._seen.pop(key, None)
            raise SemanticLoopDetectedError(
                "repeated identical tool action without progress",
                details={
                    "model": model_name,
                    "session_id": session_id,
                    "repeat_count": count,
                    "tool_signature": signature,
                },
            )
        self._seen[key] = (signature, count)


def _tool_signature(block: ToolUseBlock) -> str:
    try:
        payload = json.dumps(block.input, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except TypeError:
        payload = str(block.input)
    return f"{block.name}:{payload}"


def _response_signature(request: ChatRequest, blocks: tuple[object, ...]) -> tuple[bool, str | None]:
    del request
    for block in blocks:
        if isinstance(block, TextBlock):
            return True, None
        if isinstance(block, ToolUseBlock):
            return True, _tool_signature(block)
    return False, None


async def _peek_stream_signature(
    events: AsyncIterator[CanonicalEvent],
) -> tuple[bool, str | None, AsyncIterator[CanonicalEvent]]:
    buffered: list[CanonicalEvent] = []
    observed = False
    signature: str | None = None

    async for ev in events:
        buffered.append(ev)
        if isinstance(ev, ContentBlockStartEvent):
            if isinstance(ev.block, TextBlock):
                observed = True
                signature = None
                break
            if isinstance(ev.block, ToolUseBlock):
                observed = True
                signature = _tool_signature(ev.block)
                break

    async def replay() -> AsyncIterator[CanonicalEvent]:
        for ev in buffered:
            yield ev
        async for ev in events:
            yield ev

    return observed, signature, replay()


class MessageService:
    def __init__(
        self,
        *,
        resolver: ModelResolver,
        providers: Mapping[str, ModelProvider],
        request_preparer: RequestPreparer,
        normalizer: ResponseNormalizer,
        sequencer,
        sse_encoder: SseEncoder,
        response_encoder: ResponseEncoder,
        compatibility_mode: CompatibilityMode,
        contract_enforcer: RuntimeContractEnforcer | None = None,
        runtime_orchestrator: RuntimeOrchestrator | None = None,
        outbound_repair_policies: RuntimeOrchestrationPolicies | None = None,
        fallback_model: str | None = None,
        provider_settings: Mapping[str, ProviderSettings] | None = None,
        debug: bool = False,
    ) -> None:
        self._resolver = resolver
        self._providers = providers
        self._request_preparer = request_preparer
        self._normalizer = normalizer
        self._sequencer = sequencer
        self._sse_encoder = sse_encoder
        self._response_encoder = response_encoder
        self._compatibility_mode = compatibility_mode
        self._contract_enforcer = contract_enforcer or RuntimeContractEnforcer()
        self._runtime_orchestrator = runtime_orchestrator
        self._repair_policies = outbound_repair_policies or RuntimeOrchestrationPolicies()
        self._debug = debug
        self._fallback_model = fallback_model
        self._provider_settings = provider_settings or {}
        self._semantic_loops = _SemanticLoopTracker()

    async def stream(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> AsyncIterator[bytes]:
        try:
            return await self._stream_impl(request, provider_context)
        except (ProviderHttpError, SemanticLoopDetectedError, UpstreamTimeoutError) as exc:
            if self._fallback_model and request.model != self._fallback_model:
                _logger.warning(
                    "model_fallback_triggered",
                    extra={
                        "extra_fields": {
                            "primary_model": request.model,
                            "fallback_model": self._fallback_model,
                            "reason": exc.message,
                            "error_type": getattr(exc, "error_type", type(exc).__name__),
                        },
                    },
                )
                fallback_request = replace(request, model=self._fallback_model)
                return await self._stream_impl(fallback_request, provider_context)
            raise

    async def _stream_impl(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> AsyncIterator[bytes]:
        model, provider = self._resolve(request)
        prepared_request = self._request_preparer.prepare(request, model)
        sid = self._runtime_session_id(prepared_request, provider_context)
        tool_schemas = {t.name: t.input_schema for t in prepared_request.tools} or None
        self._validate_request(prepared_request, model)
        if self._debug:
            _logger.info(
                "stream_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(prepared_request.messages),
            )
        provider_cfg = self._provider_settings.get(model.provider)
        if provider_cfg is not None:
            events = await with_retry(
                lambda: provider.stream(prepared_request, model, provider_context),
                provider_cfg,
                operation=f"{model.provider}/stream",
            )
        else:
            events = await provider.stream(prepared_request, model, provider_context)
        normalized = self._normalizer.normalize_stream(
            prepared_request,
            model,
            events,
            self._compatibility_mode,
        )
        if self._runtime_orchestrator is not None:
            routed = runtime_orchestrate_stream(
                normalized,
                orchestrator=self._runtime_orchestrator,
                session_id=sid,
            )
            sequenced = self._sequencer.sequence(routed)
        else:
            repaired = repair_stream_tool_blocks(
                normalized, policies=self._repair_policies, tool_schemas=tool_schemas,
            )
            enforced = self._contract_enforcer.enforce_stream(repaired, model)
            sequenced = self._sequencer.sequence(enforced)
        try:
            observed, signature, sequenced = await _peek_stream_signature(sequenced)
            if observed:
                self._semantic_loops.observe(session_id=sid, model_name=request.model, signature=signature)
        except (RuntimeContractError, RuntimeOrchestrationError) as exc:
            error_chunk = self._sse_encoder.format_bridge_error_sse(exc)

            async def errored_stream() -> AsyncIterator[bytes]:
                yield error_chunk

            return errored_stream()
        encoded = self._sse_encoder.encode(sequenced)

        async def encoded_with_stream_runtime_errors() -> AsyncIterator[bytes]:
            try:
                async for chunk in encoded:
                    yield chunk
            except (RuntimeContractError, RuntimeOrchestrationError) as exc:
                # Headers may already be 200; emit the same error envelope as non-stream 422.
                yield self._sse_encoder.format_bridge_error_sse(exc)

        return encoded_with_stream_runtime_errors()

    async def complete(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> dict[str, object]:
        try:
            return await self._complete_impl(request, provider_context)
        except (ProviderHttpError, SemanticLoopDetectedError, UpstreamTimeoutError) as exc:
            if self._fallback_model and request.model != self._fallback_model:
                _logger.warning(
                    "model_fallback_triggered",
                    extra={
                        "extra_fields": {
                            "primary_model": request.model,
                            "fallback_model": self._fallback_model,
                            "reason": exc.message,
                            "error_type": getattr(exc, "error_type", type(exc).__name__),
                        },
                    },
                )
                fallback_request = replace(request, model=self._fallback_model)
                return await self._complete_impl(fallback_request, provider_context)
            raise

    async def _complete_impl(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> dict[str, object]:
        model, provider = self._resolve(request)
        prepared_request = self._request_preparer.prepare(request, model)
        sid = self._runtime_session_id(prepared_request, provider_context)
        tool_schemas = {t.name: t.input_schema for t in prepared_request.tools} or None
        self._validate_request(prepared_request, model)
        if self._debug:
            _logger.info(
                "complete_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(prepared_request.messages),
            )
        if (provider_cfg := self._provider_settings.get(model.provider)) is not None:
            response = await with_retry(
                lambda: provider.complete(prepared_request, model, provider_context),
                provider_cfg,
                operation=f"{model.provider}/complete",
            )
        else:
            response = await provider.complete(prepared_request, model, provider_context)
        normalized = self._normalizer.normalize_response(
            prepared_request,
            model,
            response,
            self._compatibility_mode,
        )
        policies = (
            self._runtime_orchestrator.policies
            if self._runtime_orchestrator is not None
            else self._repair_policies
        )
        normalized = repair_chat_response_tool_blocks(
            normalized,
            policies=policies,
            tool_schemas=tool_schemas,
        )
        if self._runtime_orchestrator is not None:
            sid = self._runtime_session_id(prepared_request, provider_context)
            session = self._runtime_orchestrator.load_or_idle(sid)
            session = self._runtime_orchestrator.on_user_turn_start(session)
            try:
                new_blocks: list[object] = []
                for i, block in enumerate(normalized.content):
                    if isinstance(block, ToolUseBlock):
                        ev = ContentBlockStartEvent(index=i, block=block)
                        _session, out = self._runtime_orchestrator.process_tool_block_start(session, ev)
                        session = _session
                        if out is not None:
                            new_blocks.append(out.block)
                    else:
                        if isinstance(block, TextBlock):
                            apply_text_control_policy(
                                text=block.text,
                                policy=self._runtime_orchestrator.policies.text_control_attempt_policy,
                            )
                            session = self._runtime_orchestrator.on_model_text_block_started(session)
                        new_blocks.append(block)
                normalized = replace(normalized, content=tuple(new_blocks))
                observed, signature = _response_signature(prepared_request, normalized.content)
                if observed:
                    self._semantic_loops.observe(session_id=sid, model_name=request.model, signature=signature)
                self._contract_enforcer.enforce_response(normalized, model)
                return self._response_encoder.encode(normalized)
            finally:
                self._runtime_orchestrator.log_upstream_turn_ended(session)

        observed, signature = _response_signature(prepared_request, normalized.content)
        if observed:
            self._semantic_loops.observe(session_id=sid, model_name=request.model, signature=signature)
        self._contract_enforcer.enforce_response(normalized, model)
        return self._response_encoder.encode(normalized)

    async def count_tokens(
        self,
        request: ChatRequest,
        provider_context: ProviderRequestContext | None = None,
    ) -> dict[str, int]:
        model, provider = self._resolve(request)
        prepared_request = self._request_preparer.prepare(request, model)
        self._validate_request(prepared_request, model)
        if self._debug:
            _logger.info(
                "count_tokens_start model=%s provider=%s compatibility=%s messages=%d",
                model.name,
                model.provider,
                self._compatibility_mode.value,
                len(prepared_request.messages),
            )
        input_tokens = await provider.count_tokens(prepared_request, model, provider_context)
        return {"input_tokens": input_tokens}

    def _resolve(self, request: ChatRequest) -> tuple[ModelInfo, ModelProvider]:
        model = self._resolver.resolve(request.model)
        provider = self._providers.get(model.provider)
        if provider is None:
            raise RoutingError(f"provider '{model.provider}' is not configured")
        return model, provider

    @staticmethod
    def _runtime_session_id(request: ChatRequest, ctx: ProviderRequestContext | None) -> str:
        header_sid: str | None = None
        if ctx is not None:
            for key, value in ctx.headers:
                if key.lower() == "x-llm-proxy-runtime-session":
                    header_sid = value
                    break
        md = dict(request.metadata) if request.metadata is not None else None
        return effective_runtime_session_id(metadata=md, header_session_id=header_sid)

    def _validate_request(self, request: ChatRequest, model: ModelInfo) -> None:
        if request.stream and not model.supports_stream:
            raise RoutingError(f"model '{model.name}' does not support streaming")
        if not request.stream and not model.supports_nonstream:
            raise RoutingError(f"model '{model.name}' does not support non-stream responses")
        if request.tools and not model.supports_tools:
            raise RoutingError(f"model '{model.name}' does not support tools")
        if request.thinking and not model.supports_thinking:
            raise RoutingError(f"model '{model.name}' does not support thinking")
