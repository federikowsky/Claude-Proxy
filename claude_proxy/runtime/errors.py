"""Runtime orchestration errors."""

from __future__ import annotations

from claude_proxy.domain.errors import BridgeError


class RuntimeOrchestrationError(BridgeError):
    status_code = 422
    error_type = "runtime_orchestration_error"


class InvalidRuntimeTransitionError(RuntimeOrchestrationError):
    error_type = "invalid_runtime_transition"


class RuntimeInvariantViolationError(RuntimeOrchestrationError):
    error_type = "runtime_invariant_violation"


class RuntimeRecoveryError(RuntimeOrchestrationError):
    error_type = "runtime_recovery_error"


class InvalidToolSchemaContractError(RuntimeOrchestrationError):
    error_type = "invalid_tool_schema_contract"


class InvalidModelRuntimeActionError(RuntimeOrchestrationError):
    error_type = "invalid_model_runtime_action"


class CapabilityNotImplementedInBridgeError(RuntimeOrchestrationError):
    """Registry row is not executable in the bridge (e.g. inventory-only)."""

    error_type = "capability_not_implemented_in_bridge"


class RuntimeOrchestrationDisabledError(BridgeError):
    status_code = 503
    error_type = "runtime_orchestration_disabled"
