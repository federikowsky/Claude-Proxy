from __future__ import annotations

import asyncio

import httpx

from claude_proxy.infrastructure.config import Settings


class SharedAsyncClientManager:
    def __init__(
        self,
        settings: Settings,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._settings = settings
        self._transport = transport
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    async def get_client(self) -> httpx.AsyncClient:
        if self._client is not None:
            return self._client

        async with self._lock:
            if self._client is None:
                self._client = httpx.AsyncClient(
                    headers={"User-Agent": "claude-proxy/0.1.0"},
                    limits=self._limits(),
                    timeout=httpx.Timeout(self._settings.server.request_timeout_seconds),
                    transport=self._transport,
                )
        return self._client

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _limits(self) -> httpx.Limits:
        enabled = [
            provider
            for provider in self._settings.providers.values()
            if provider.enabled
        ]
        max_connections = max(provider.max_connections for provider in enabled)
        max_keepalive_connections = max(provider.max_keepalive_connections for provider in enabled)
        return httpx.Limits(
            max_connections=max_connections,
            max_keepalive_connections=max_keepalive_connections,
        )

