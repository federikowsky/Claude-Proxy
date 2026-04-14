from __future__ import annotations

import pytest

from llm_proxy.domain.errors import RoutingError
from llm_proxy.infrastructure.resolvers import StaticModelResolver


def test_resolver_returns_model_info(settings) -> None:
    resolver = StaticModelResolver(settings)
    model = resolver.resolve("anthropic/claude-sonnet-4")
    assert model.name == "anthropic/claude-sonnet-4"
    assert model.supports_stream is True
    assert model.supports_nonstream is True


def test_resolver_rejects_unknown_model(settings) -> None:
    resolver = StaticModelResolver(settings)
    with pytest.raises(RoutingError):
        resolver.resolve("unknown/model")

