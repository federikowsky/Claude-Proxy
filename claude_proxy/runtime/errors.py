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


class RuntimeOrchestrationDisabledError(BridgeError):
    status_code = 503
    error_type = "runtime_orchestration_disabled"
