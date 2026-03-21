from __future__ import annotations

import pytest

from claude_proxy.domain.errors import RoutingError
from claude_proxy.infrastructure.resolvers import StaticModelResolver


def test_resolver_returns_model_info(settings) -> None:
    resolver = StaticModelResolver(settings)
    model = resolver.resolve("openai/gpt-4.1-mini")
    assert model.name == "openai/gpt-4.1-mini"
    assert model.provider == "openrouter"


def test_resolver_rejects_unknown_model(settings) -> None:
    resolver = StaticModelResolver(settings)
    with pytest.raises(RoutingError):
        resolver.resolve("unknown/model")

