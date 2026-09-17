"""Typed API failures rendered as RFC 9457 problem details.

Every rejection a caller can provoke is one of these, so an error response
always names *which* rule was hit rather than returning a bare status code. The
quota failures carry their numbers for the same reason: a limit error that does
not say what the limit was is a support ticket.
"""

from typing import Any


class HubError(Exception):
    """Base class for a failure that maps onto an HTTP problem response."""

    status: int = 400
    code: str = "bad_request"

    def __init__(self, detail: str, **extra: object) -> None:
        """Record the human-readable ``detail`` and any machine fields."""
        super().__init__(detail)
        self.detail = detail
        self.extra = extra

    def problem(self, instance: str) -> dict[str, Any]:
        """Return the problem-details body for this failure."""
        body: dict[str, Any] = {
            "type": f"https://hub.spikeforge.net/errors/{self.code}",
            "title": self.code.replace("_", " "),
            "status": self.status,
            "detail": self.detail,
            "instance": instance,
        }
        body.update(self.extra)
        return body


class UnauthorizedError(HubError):
    """No usable credential was presented."""

    status = 401
    code = "unauthorized"


class ForbiddenError(HubError):
    """A valid credential lacks the scope or ownership required."""

    status = 403
    code = "forbidden"


class NotFoundError(HubError):
    """The addressed resource does not exist, or is not visible."""

    status = 404
    code = "not_found"


class ConflictError(HubError):
    """The resource already exists, or the state transition is not legal."""

    status = 409
    code = "conflict"


class QuotaExceededError(HubError):
    """A per-account or service-wide storage limit refused the request."""

    status = 413
    code = "quota_exceeded"


class UnprocessableUploadError(HubError):
    """Uploaded bytes did not match what the reservation described."""

    status = 422
    code = "unprocessable_upload"


class RateLimitedError(HubError):
    """The caller exceeded a request or upload rate limit."""

    status = 429
    code = "rate_limited"


class InvalidRequestError(HubError):
    """An OAuth request is malformed: a bad parameter, or one missing."""

    status = 400
    code = "invalid_request"


class AuthorizationPendingError(HubError):
    """A device-code poll arrived before a person approved it."""

    status = 400
    code = "authorization_pending"


class SlowDownError(HubError):
    """A device-code poll arrived faster than the required interval."""

    status = 429
    code = "slow_down"


class ServiceUnavailableError(HubError):
    """A dependency the request needs is not currently usable."""

    status = 503
    code = "service_unavailable"
