"""Tests for retry with exponential backoff and automatic model fallback."""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from llm_proxy.domain.errors import (
    ProviderHttpError,
    RoutingError,
    UpstreamTimeoutError,
)
from llm_proxy.infrastructure.config import ProviderSettings
from llm_proxy.infrastructure.retry import _backoff_delay, with_retry


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider_settings(*, retry_attempts: int = 2, retry_backoff_base: float = 1.0) -> ProviderSettings:
    return ProviderSettings(
        base_url="https://api.example.com",
        api_key_env="TEST_KEY",
        api_key="test",
        connect_timeout_seconds=5,
        read_timeout_seconds=30,
        write_timeout_seconds=10,
        pool_timeout_seconds=5,
        max_connections=10,
        max_keepalive_connections=5,
        retry_attempts=retry_attempts,
        retry_backoff_base=retry_backoff_base,
    )


# ---------------------------------------------------------------------------
# Retry tests (with_retry directly)
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_retry_succeeds_on_second_attempt():
    """First call fails with 429, second succeeds."""
    fn = AsyncMock(side_effect=[
        ProviderHttpError("rate limited", upstream_status=429, provider="test"),
        "success",
    ])
    with patch("llm_proxy.infrastructure.retry.asyncio.sleep", new_callable=AsyncMock):
        result = await with_retry(fn, _provider_settings())

    assert result == "success"
    assert fn.call_count == 2


@pytest.mark.anyio
async def test_retry_exhausted_raises():
    """All attempts fail → last error raised."""
    exc = ProviderHttpError("rate limited", upstream_status=429, provider="test")
    fn = AsyncMock(side_effect=exc)
    with patch("llm_proxy.infrastructure.retry.asyncio.sleep", new_callable=AsyncMock):
        with pytest.raises(ProviderHttpError):
            await with_retry(fn, _provider_settings(retry_attempts=2))

    assert fn.call_count == 3  # 1 initial + 2 retries


@pytest.mark.anyio
async def test_no_retry_on_non_retryable_status():
    """400 (not in retry_on_status) → immediate raise, no retry."""
    fn = AsyncMock(side_effect=ProviderHttpError("bad request", upstream_status=400, provider="test"))
    with pytest.raises(ProviderHttpError):
        await with_retry(fn, _provider_settings())

    assert fn.call_count == 1


@pytest.mark.anyio
async def test_retry_disabled_with_zero_attempts():
    """retry_attempts=0 → exactly 1 call, then raise."""
    fn = AsyncMock(side_effect=ProviderHttpError("rate limited", upstream_status=429, provider="test"))
    with pytest.raises(ProviderHttpError):
        await with_retry(fn, _provider_settings(retry_attempts=0))

    assert fn.call_count == 1


@pytest.mark.anyio
async def test_retry_respects_retry_after():
    """Retry-After value from error is used as sleep delay."""
    exc = ProviderHttpError("rate limited", upstream_status=429, provider="test", retry_after=3.0)
    fn = AsyncMock(side_effect=[exc, "ok"])
    with patch("llm_proxy.infrastructure.retry.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        await with_retry(fn, _provider_settings())

    mock_sleep.assert_called_once_with(3.0)


@pytest.mark.anyio
async def test_retry_on_timeout():
    """UpstreamTimeoutError is retried."""
    fn = AsyncMock(side_effect=[
        UpstreamTimeoutError("timeout"),
        "ok",
    ])
    with patch("llm_proxy.infrastructure.retry.asyncio.sleep", new_callable=AsyncMock):
        result = await with_retry(fn, _provider_settings(retry_attempts=1))

    assert result == "ok"
    assert fn.call_count == 2


def test_backoff_exponential():
    """Backoff increases exponentially with jitter."""
    d0 = _backoff_delay(0, 1.0)
    assert 1.0 <= d0 <= 1.25

    d1 = _backoff_delay(1, 1.0)
    assert 2.0 <= d1 <= 2.5

    d2 = _backoff_delay(2, 1.0)
    assert 4.0 <= d2 <= 5.0


# ---------------------------------------------------------------------------
# Fallback tests (MessageService level)
# ---------------------------------------------------------------------------

def _make_service(*, fallback_model: str | None = None, fail_primary: bool = True):
    """Create a MessageService with mocked dependencies for fallback testing."""
    from llm_proxy.application.services import MessageService
    from llm_proxy.domain.models import ModelInfo
    from llm_proxy.domain.enums import (
        ActionPolicy,
        CompatibilityMode,
        ThinkingPassthroughMode,
    )

    primary_model = ModelInfo(
        name="primary/model",
        provider="primary_provider",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
        thinking_passthrough_mode=ThinkingPassthroughMode.FULL,
    )
    fallback_model_info = ModelInfo(
        name="fallback/model",
        provider="fallback_provider",
        enabled=True,
        supports_stream=True,
        supports_nonstream=True,
        supports_tools=True,
        supports_thinking=True,
        thinking_passthrough_mode=ThinkingPassthroughMode.FULL,
    )

    resolver = MagicMock()

    def resolve_side_effect(model_name):
        if model_name == "primary/model":
            return primary_model
        if model_name == "fallback/model":
            return fallback_model_info
        raise RoutingError(f"unknown model {model_name}")

    resolver.resolve = MagicMock(side_effect=resolve_side_effect)

    primary_provider = AsyncMock()
    fallback_provider = AsyncMock()

    if fail_primary:
        primary_provider.stream = AsyncMock(
            side_effect=ProviderHttpError("error", upstream_status=502, provider="primary_provider"),
        )
        primary_provider.complete = AsyncMock(
            side_effect=ProviderHttpError("error", upstream_status=502, provider="primary_provider"),
        )

    # Minimal mock that returns compatible objects
    async def mock_stream_iter():
        yield b"data: test\n\n"

    fallback_provider.stream = AsyncMock(return_value=mock_stream_iter())
    fallback_provider.complete = AsyncMock(return_value=MagicMock())

    providers = {
        "primary_provider": primary_provider,
        "fallback_provider": fallback_provider,
    }

    preparer = MagicMock()
    preparer.prepare = MagicMock(side_effect=lambda req, model: req)

    normalizer = MagicMock()

    async def norm_stream_iter():
        yield MagicMock()

    normalizer.normalize_stream = MagicMock(return_value=norm_stream_iter())
    normalizer.normalize_response = MagicMock(return_value=MagicMock(content=()))

    sequencer = MagicMock()

    async def seq_iter():
        yield MagicMock()

    sequencer.sequence = MagicMock(return_value=seq_iter())

    sse_encoder = MagicMock()

    async def enc_iter():
        yield b"data: test\n\n"

    sse_encoder.encode = MagicMock(return_value=enc_iter())

    response_encoder = MagicMock()
    response_encoder.encode = MagicMock(return_value={"type": "message"})

    service = MessageService(
        resolver=resolver,
        providers=providers,
        request_preparer=preparer,
        normalizer=normalizer,
        sequencer=sequencer,
        sse_encoder=sse_encoder,
        response_encoder=response_encoder,
        compatibility_mode=CompatibilityMode.TRANSPARENT,
        fallback_model=fallback_model,
    )

    return service, primary_provider, fallback_provider


def _chat_request(model: str = "primary/model", *, stream: bool = True):
    from llm_proxy.domain.models import ChatRequest, Message, Role
    return ChatRequest(
        model=model,
        messages=(Message(role=Role.USER, content="hello"),),
        system=None,
        metadata=None,
        temperature=None,
        top_p=None,
        max_tokens=1024,
        stop_sequences=(),
        tools=(),
        tool_choice=None,
        thinking=None,
        stream=stream,
    )


@pytest.mark.anyio
async def test_fallback_on_provider_failure():
    """Primary fails → fallback provider is called for stream."""
    service, primary, fallback = _make_service(fallback_model="fallback/model")
    result = await service.stream(_chat_request())
    # Stream was returned (from fallback path)
    assert result is not None
    fallback.stream.assert_called_once()


@pytest.mark.anyio
async def test_no_fallback_when_model_is_fallback():
    """When request model == fallback model, error raised directly."""
    service, _, fallback = _make_service(fallback_model="primary/model")
    with pytest.raises(ProviderHttpError):
        await service.stream(_chat_request(model="primary/model"))
    fallback.stream.assert_not_called()


@pytest.mark.anyio
async def test_no_fallback_on_routing_error():
    """RoutingError is not caught for fallback."""
    from llm_proxy.application.services import MessageService
    from llm_proxy.domain.enums import CompatibilityMode

    resolver = MagicMock()
    resolver.resolve = MagicMock(side_effect=RoutingError("no such model"))

    service = MessageService(
        resolver=resolver,
        providers={},
        request_preparer=MagicMock(),
        normalizer=MagicMock(),
        sequencer=MagicMock(),
        sse_encoder=MagicMock(),
        response_encoder=MagicMock(),
        compatibility_mode=CompatibilityMode.TRANSPARENT,
        fallback_model="fallback/model",
    )

    with pytest.raises(RoutingError):
        await service.stream(_chat_request())


@pytest.mark.anyio
async def test_no_fallback_when_not_configured():
    """Without fallback_model, error raised directly."""
    service, _, fallback = _make_service(fallback_model=None)
    with pytest.raises(ProviderHttpError):
        await service.stream(_chat_request())
    fallback.stream.assert_not_called()


@pytest.mark.anyio
async def test_fallback_complete_path():
    """Primary fails on complete → fallback provider is called."""
    service, primary, fallback = _make_service(fallback_model="fallback/model")
    result = await service.complete(_chat_request(stream=False))
    assert result is not None
    fallback.complete.assert_called_once()
