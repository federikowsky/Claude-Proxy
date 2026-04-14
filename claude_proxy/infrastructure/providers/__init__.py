from __future__ import annotations

from collections.abc import Mapping

from claude_proxy.domain.errors import RoutingError
from claude_proxy.domain.ports import ModelProvider
from claude_proxy.infrastructure.config import Settings
from claude_proxy.infrastructure.http import SharedAsyncClientManager
from claude_proxy.infrastructure.providers.anthropic import AnthropicProvider, AnthropicTranslator
from claude_proxy.infrastructure.providers.openai_compat import OpenAICompatProvider, OpenAICompatTranslator
from claude_proxy.infrastructure.providers.openrouter import OpenRouterProvider, OpenRouterTranslator


def build_provider_registry(
    settings: Settings,
    client_manager: SharedAsyncClientManager,
) -> Mapping[str, ModelProvider]:
    builders = {
        "openrouter": lambda provider_settings: OpenRouterProvider(
            settings=provider_settings,
            client_manager=client_manager,
            translator=OpenRouterTranslator(),
        ),
        "anthropic": lambda provider_settings: AnthropicProvider(
            settings=provider_settings,
            client_manager=client_manager,
            translator=AnthropicTranslator(),
        ),
        "nvidia": lambda provider_settings: OpenAICompatProvider(
            settings=provider_settings,
            client_manager=client_manager,
            translator=OpenAICompatTranslator("nvidia"),
            provider_name="nvidia",
        ),
        "gemini": lambda provider_settings: OpenAICompatProvider(
            settings=provider_settings,
            client_manager=client_manager,
            translator=OpenAICompatTranslator("gemini"),
            provider_name="gemini",
        ),
    }
    providers: dict[str, ModelProvider] = {}
    for provider_name, provider_settings in settings.providers.items():
        if not provider_settings.enabled:
            continue
        builder = builders.get(provider_name)
        if builder is None:
            raise RoutingError(f"provider '{provider_name}' has no registered adapter")
        providers[provider_name] = builder(provider_settings)
    return providers
