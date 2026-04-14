"""Request preparation layer.

Responsibilities:
- Validate and strip extension fields not supported by the target model.
- Normalize tool input_schema for every tool before provider emission.
- Annotate tool definitions with their ToolCategory.
- Enforce the provider-boundary schema invariant (hard failure).
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import replace

from llm_proxy.application.tool_classifier import ToolClassifier, get_default_classifier
from llm_proxy.domain.errors import ProviderBoundaryError, RequestValidationError
from llm_proxy.domain.models import ChatRequest, ModelInfo, ToolDefinition
from llm_proxy.domain.serialization import normalize_tool_schema

_logger = logging.getLogger("llm_proxy.request")


class ModelAwareRequestPreparer:
    """Prepare a :class:`ChatRequest` for dispatch to a provider.

    Steps (applied in order):
    1. Validate extension fields against the configured allow-list.
    2. Strip extension fields unsupported by the target model.
    3. Normalise tool input_schema for every tool definition.
    4. Annotate tool definitions with their :class:`ToolCategory`.
    5. Enforce the provider-boundary schema invariant (hard failure if violated).

    The method returns the original request object unchanged if steps 2-4
    produce no mutations (identity preserved in the common case).
    """

    def __init__(
        self,
        *,
        allowed_request_fields: Sequence[str] = (),
        tool_classifier: ToolClassifier | None = None,
    ) -> None:
        self._allowed_request_fields = set(allowed_request_fields)
        self._tool_classifier = tool_classifier or get_default_classifier()

    def prepare(self, request: ChatRequest, model: ModelInfo) -> ChatRequest:
        self._validate_extension_fields(request)
        sanitized_extensions, stripped_fields = self._sanitize_extensions(request, model)
        if stripped_fields:
            _logger.debug(
                "request_fields_stripped model=%s fields=%s",
                model.name,
                ",".join(stripped_fields),
                extra={
                    "extra_fields": {
                        "model": model.name,
                        "stripped_fields": stripped_fields,
                    },
                },
            )

        normalized_tools, tools_changed = self._normalize_tools(request.tools, model)

        # Enforce provider-boundary schema invariant — hard failure on violation.
        self._assert_schema_invariant(normalized_tools)

        # Preserve object identity when nothing changed.
        if not stripped_fields and not tools_changed:
            return request

        return replace(
            request,
            extensions=sanitized_extensions,
            tools=normalized_tools,
        )

    # ------------------------------------------------------------------
    # Extension field handling
    # ------------------------------------------------------------------

    def _validate_extension_fields(self, request: ChatRequest) -> None:
        unknown_fields = set(request.extensions) - self._allowed_request_fields
        if not unknown_fields:
            return
        names = ", ".join(sorted(unknown_fields))
        raise RequestValidationError(f"unsupported request passthrough fields: {names}")

    def _sanitize_extensions(
        self,
        request: ChatRequest,
        model: ModelInfo,
    ) -> tuple[dict[str, object], list[str]]:
        unsupported_fields = set(model.unsupported_request_fields)
        if not unsupported_fields:
            return dict(request.extensions), []

        sanitized = dict(request.extensions)
        stripped_fields = [field for field in request.extensions if field in unsupported_fields]
        for field in stripped_fields:
            sanitized.pop(field, None)
        return sanitized, stripped_fields

    # ------------------------------------------------------------------
    # Tool schema normalisation + category annotation
    # ------------------------------------------------------------------

    def _normalize_tools(
        self,
        tools: tuple[ToolDefinition, ...],
        model: ModelInfo,
    ) -> tuple[tuple[ToolDefinition, ...], bool]:
        """Return (normalised_tools, changed).

        Normalises the input_schema of every tool definition and annotates it with
        its :class:`ToolCategory`.  Returns the original tuple unchanged (identity)
        when no modifications are needed.
        """
        if not tools:
            return tools, False

        result: list[ToolDefinition] = []
        changed = False

        for tool in tools:
            normalised_schema = normalize_tool_schema(tool.input_schema, tool_name=tool.name)
            # Annotate category
            category = self._tool_classifier.classify(tool)

            schema_changed = normalised_schema != dict(tool.input_schema)
            category_changed = tool.category is not category

            if schema_changed or category_changed:
                result.append(
                    replace(tool, input_schema=normalised_schema, category=category)
                )
                changed = True
            else:
                result.append(tool)

        return tuple(result), changed

    # ------------------------------------------------------------------
    # Provider-boundary schema invariant
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_schema_invariant(tools: tuple[ToolDefinition, ...]) -> None:
        """Hard invariant: every tool must have a non-empty mapping input_schema.

        Raises :class:`ProviderBoundaryError` immediately on first violation.
        This check runs after normalisation, so a violation here indicates a bug
        in the normalisation logic itself.
        """
        for tool in tools:
            schema = tool.input_schema
            if not isinstance(schema, Mapping) or not schema:
                raise ProviderBoundaryError(
                    f"provider boundary invariant violated: tool '{tool.name}' "
                    f"has invalid input_schema after normalisation",
                    details={"tool": tool.name, "schema": repr(schema)},
                )
