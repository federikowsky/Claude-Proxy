from __future__ import annotations

from claude_proxy.domain.errors import RoutingError
from claude_proxy.domain.models import ModelInfo
from claude_proxy.infrastructure.config import Settings


class StaticModelResolver:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def resolve(self, requested_model: str | None) -> ModelInfo:
        model_name = requested_model or self._settings.routing.default_model
        config = self._settings.models.get(model_name)
        if config is None:
            raise RoutingError(f"model '{model_name}' is not configured")
        if not config.enabled:
            raise RoutingError(f"model '{model_name}' is disabled")
        return ModelInfo(
            name=model_name,
            provider=config.provider,
            enabled=config.enabled,
            supports_stream=config.supports_stream,
            supports_nonstream=config.supports_nonstream,
            supports_tools=config.supports_tools,
            supports_thinking=config.supports_thinking,
            thinking_passthrough_mode=config.thinking_passthrough_mode,
            unsupported_request_fields=config.unsupported_request_fields,
            schema_normalization_policy=config.schema_normalization_policy,
            control_action_policy=config.control_action_policy,
            orchestration_action_policy=config.orchestration_action_policy,
            generic_tool_emulation_policy=config.generic_tool_emulation_policy,
        )
