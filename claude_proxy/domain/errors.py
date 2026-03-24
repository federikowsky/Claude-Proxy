from __future__ import annotations

from collections.abc import Mapping


class BridgeError(Exception):
    status_code = 500
    error_type = "internal_error"

    def __init__(
        self,
        message: str,
        *,
        details: Mapping[str, object] | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.details = dict(details or {})
        if status_code is not None:
            self.status_code = status_code

    def to_payload(self) -> dict[str, object]:
        error = {
            "type": self.error_type,
            "message": self.message,
            **self.details,
        }
        return {
            "type": "error",
            "error": error,
        }


class RequestValidationError(BridgeError):
    status_code = 400
    error_type = "invalid_request_error"


class RoutingError(BridgeError):
    status_code = 422
    error_type = "routing_error"


class ProviderProtocolError(BridgeError):
    status_code = 502
    error_type = "provider_protocol_error"


class ProviderAuthError(BridgeError):
    status_code = 502
    error_type = "provider_auth_error"


class ProviderHttpError(BridgeError):
    status_code = 502
    error_type = "provider_http_error"

    def __init__(self, message: str, *, upstream_status: int, provider: str) -> None:
        translated_status = upstream_status if 400 <= upstream_status < 500 else 502
        if upstream_status in {401, 403}:
            translated_status = 502
        super().__init__(
            message,
            status_code=translated_status,
            details={
                "provider": provider,
                "upstream_status": upstream_status,
            },
        )


class UpstreamTimeoutError(BridgeError):
    status_code = 504
    error_type = "upstream_timeout"


class InternalBridgeError(BridgeError):
    status_code = 500
    error_type = "internal_bridge_error"


class ProviderBoundaryError(BridgeError):
    """Raised when a provider-boundary invariant is violated before payload emission.

    This is a hard failure: the system cannot safely emit a payload that would
    violate the contract the provider expects.
    """

    status_code = 500
    error_type = "provider_boundary_error"


class RuntimeContractError(BridgeError):
    """Raised when the runtime contract enforcer detects an invalid or ambiguous action.

    This represents a hard failure: the proxy detected that a model-emitted action
    violates the runtime contract and cannot be safely forwarded or interpreted.
    """

    status_code = 422
    error_type = "runtime_contract_error"


class TextControlAttemptBlockedError(RuntimeContractError):
    """Raised when ``text_control_attempt_policy`` is ``block`` and plain text matches control phrases."""

    error_type = "text_control_attempt_blocked"
