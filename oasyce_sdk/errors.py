"""Custom exception hierarchy for the Oasyce SDK.

All exceptions inherit from OasyceError so callers can catch broadly
or narrow down to specific failure modes.
"""

from __future__ import annotations


class OasyceError(Exception):
    """Base exception for all Oasyce SDK errors."""


class ConnectionError(OasyceError):
    """Raised when the SDK cannot reach the chain node."""


class TimeoutError(OasyceError):
    """Raised when a request to the chain node times out."""


class NotFoundError(OasyceError):
    """Raised when the requested resource does not exist on-chain (HTTP 404 / gRPC NOT_FOUND)."""

    def __init__(self, resource_type: str, resource_id: str) -> None:
        self.resource_type = resource_type
        self.resource_id = resource_id
        super().__init__(f"{resource_type} not found: {resource_id}")


class ChainError(OasyceError):
    """Raised when the chain returns an application-level error (non-zero code)."""

    def __init__(self, code: int, raw_log: str) -> None:
        self.code = code
        self.raw_log = raw_log
        super().__init__(f"chain error (code {code}): {raw_log}")


class HTTPError(OasyceError):
    """Raised for unexpected HTTP status codes from the REST gateway."""

    def __init__(self, status_code: int, body: str) -> None:
        self.status_code = status_code
        self.body = body
        super().__init__(f"HTTP {status_code}: {body}")


class ValidationError(OasyceError):
    """Raised when input validation fails before sending a request."""
