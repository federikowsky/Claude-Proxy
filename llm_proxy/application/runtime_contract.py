"""Runtime contract enforcement layer.

This module is the primary enforcement point that inspects model-emitted content
and enforces the runtime contract before the response is forwarded to the client.

Responsibilities
----------------
* Iterate response content blocks looking for ``ToolUseBlock`` instances.
* Classify each tool-use block using :class:`~llm_proxy.application.runtime_actions.RuntimeActionClassifier`.
* Apply the per-model capability policy for each action category:
  - ``ALLOW``   → pass through silently.
  - ``WARN``    → emit a structured log warning and pass through.
  - ``BLOCK``   → raise :class:`~llm_proxy.domain.errors.RuntimeContractError`.
* For ``INVALID_ACTION`` specifically: always honour ``generic_tool_emulation_policy``.
* For ``STATE_TRANSITION``: honour ``control_action_policy``.
* For ``ORCHESTRATION_ACTION``: honour ``orchestration_action_policy``.
* For ``TOOL_CALL``: always ALLOW.
* For ``FINALIZATION_ACTION``: always ALLOW (the model legitimately wants to finish).
* For ``NO_OP``: always ALLOW.

The enforcer is deterministic: given the same model policy and tool content, it
always produces the same classification and policy decision.

Usage
-----
Create one instance and reuse it.  Call :meth:`enforce_response` after receiving a
non-streaming completed response, or :meth:`enforce_tool_use_block` per block for
incremental enforcement.
"""

from __future__ import annotations

import logging

from collections.abc import AsyncIterator

from llm_proxy.application.runtime_actions import RuntimeAction, RuntimeActionClassifier
from llm_proxy.domain.enums import ActionPolicy, RuntimeActionType
from llm_proxy.domain.errors import RuntimeContractError
from llm_proxy.domain.models import (
    CanonicalEvent,
    ChatResponse,
    ContentBlockStartEvent,
    ModelInfo,
    ToolUseBlock,
)

_logger = logging.getLogger("llm_proxy.contract")


class RuntimeContractEnforcer:
    """Apply capability-policy-driven runtime contract enforcement to model output.

    Parameters
    ----------
    action_classifier:
        The :class:`~llm_proxy.application.runtime_actions.RuntimeActionClassifier`
        to use.  If not provided, a new default instance is created.
    """

    def __init__(self, action_classifier: RuntimeActionClassifier | None = None) -> None:
        self._classifier = action_classifier or RuntimeActionClassifier()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enforce_response(self, response: ChatResponse, model: ModelInfo) -> ChatResponse:
        """Enforce the runtime contract on a completed non-streaming response.

        Iterates all content blocks; raises :class:`RuntimeContractError` on the
        first policy violation.  Returns the response unchanged (identity) if all
        blocks pass enforcement.
        """
        for block in response.content:
            if isinstance(block, ToolUseBlock):
                action = self._classifier.classify(block)
                self._apply_policy(action, model)
        return response

    def enforce_tool_use_block(self, block: ToolUseBlock, model: ModelInfo) -> RuntimeAction:
        """Classify and enforce policy for a single tool-use block.

        Returns the :class:`RuntimeAction` if the block passes enforcement so that
        callers can inspect the classification result.  Raises
        :class:`RuntimeContractError` on policy violation.
        """
        action = self._classifier.classify(block)
        self._apply_policy(action, model)
        return action

    async def enforce_stream(
        self,
        events: AsyncIterator[CanonicalEvent],
        model: ModelInfo,
    ) -> AsyncIterator[CanonicalEvent]:
        """Async generator: enforce runtime contract on a canonical event stream.

        Inspects each :class:`ContentBlockStartEvent`.  If the block is a
        :class:`ToolUseBlock`, it is classified and the model's policy is applied:

        - ``ALLOW`` → yield unchanged.
        - ``WARN``  → log + yield unchanged.
        - ``BLOCK`` → raise :class:`RuntimeContractError` (stream aborts).

        All other events are yielded unchanged without classification overhead.
        """
        async for event in events:
            if isinstance(event, ContentBlockStartEvent) and isinstance(event.block, ToolUseBlock):
                # enforce_tool_use_block raises on BLOCK; we re-raise cleanly.
                self.enforce_tool_use_block(event.block, model)
            yield event

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _apply_policy(self, action: RuntimeAction, model: ModelInfo) -> None:
        """Apply the per-model policy for *action*.

        Raises :class:`RuntimeContractError` if the resolved policy is ``BLOCK``.
        """
        policy = self._resolve_policy(action, model)

        if policy is ActionPolicy.ALLOW:
            return

        log_context = {
            "tool": action.tool_name,
            "action_type": action.action_type,
            "category": action.tool_category,
            "policy": policy,
            "model": model.name,
            "diagnostic": action.diagnostic,
        }

        if policy is ActionPolicy.WARN:
            _logger.warning(
                "runtime_contract_warn model=%s tool=%s action=%s: %s",
                model.name,
                action.tool_name,
                action.action_type,
                action.diagnostic or "no diagnostic",
                extra={"extra_fields": log_context},
            )
            return

        # BLOCK
        _logger.error(
            "runtime_contract_block model=%s tool=%s action=%s: %s",
            model.name,
            action.tool_name,
            action.action_type,
            action.diagnostic or "no diagnostic",
            extra={"extra_fields": log_context},
        )
        raise RuntimeContractError(
            f"runtime contract violation: {action.diagnostic or action.action_type}",
            details={
                "tool": action.tool_name,
                "action_type": action.action_type,
                "model": model.name,
            },
        )

    @staticmethod
    def _resolve_policy(action: RuntimeAction, model: ModelInfo) -> ActionPolicy:
        """Return the effective :class:`ActionPolicy` for *action* under *model*."""
        action_type = action.action_type

        if action_type is RuntimeActionType.TOOL_CALL:
            return ActionPolicy.ALLOW

        if action_type is RuntimeActionType.STATE_TRANSITION:
            return model.control_action_policy

        if action_type is RuntimeActionType.ORCHESTRATION_ACTION:
            return model.orchestration_action_policy

        if action_type is RuntimeActionType.INVALID_ACTION:
            return model.generic_tool_emulation_policy

        if action_type in (RuntimeActionType.FINALIZATION_ACTION, RuntimeActionType.NO_OP):
            return ActionPolicy.ALLOW

        # Unknown action type — treat conservatively as WARN.
        return ActionPolicy.WARN
