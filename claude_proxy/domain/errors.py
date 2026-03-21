from __future__ import annotations


class BridgeError(Exception):
    status_code = 500
    error_type = "internal_error"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message

    def to_payload(self) -> dict[str, object]:
        return {
            "type": "error",
            "error": {
                "type": self.error_type,
                "message": self.message,
            },
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


class UpstreamTimeoutError(BridgeError):
    status_code = 504
    error_type = "upstream_timeout"


class InternalBridgeError(BridgeError):
    status_code = 500
    error_type = "internal_bridge_error"

