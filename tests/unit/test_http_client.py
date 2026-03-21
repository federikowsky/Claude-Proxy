from __future__ import annotations

import pytest

from claude_proxy.infrastructure.http import SharedAsyncClientManager


@pytest.mark.asyncio
async def test_http_client_manager_reuses_single_client(settings) -> None:
    manager = SharedAsyncClientManager(settings)
    try:
        client_a = await manager.get_client()
        client_b = await manager.get_client()
        assert client_a is client_b
    finally:
        await manager.close()

