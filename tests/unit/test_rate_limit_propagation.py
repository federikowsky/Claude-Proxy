"""Tests for Retry-After header propagation on rate-limited responses."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from llm_proxy.api.errors import install_error_handlers
from llm_proxy.domain.errors import ProviderHttpError


def _make_test_app(*, upstream_status: int = 429, retry_after: float | None = None):
    """Minimal app that raises ProviderHttpError on /trigger."""
    app = FastAPI()
    install_error_handlers(app)

    @app.get("/trigger")
    async def trigger():
        raise ProviderHttpError(
            "rate limited",
            upstream_status=upstream_status,
            provider="test-provider",
            retry_after=retry_after,
        )

    return app


@pytest.mark.anyio
async def test_retry_after_header_on_429():
    """429 with retry_after=30 → Retry-After: 30 header."""
    app = _make_test_app(upstream_status=429, retry_after=30.0)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/trigger")

    assert resp.status_code == 429
    assert resp.headers.get("retry-after") == "30"


@pytest.mark.anyio
async def test_no_retry_after_on_500():
    """500 without retry_after → no Retry-After header."""
    app = _make_test_app(upstream_status=500, retry_after=None)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/trigger")

    assert resp.status_code == 502  # 500 translates to 502
    assert "retry-after" not in resp.headers


@pytest.mark.anyio
async def test_retry_after_integer_format():
    """Fractional retry_after=30.7 rounds down to integer '30'."""
    app = _make_test_app(upstream_status=429, retry_after=30.7)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/trigger")

    assert resp.headers.get("retry-after") == "30"
