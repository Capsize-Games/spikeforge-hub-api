"""The verification sandbox's callback: pass, fail, or refuse the call.

Mounted under ``/internal/v1`` rather than ``/v1``: this route does not
authenticate through the cookie/bearer flow every other write path uses
(:mod:`hub_api.deps`), because its caller is not a hub account. Its only
credential is an HMAC-SHA256 signature over the raw request body, keyed
with ``config.verification_secret`` -- the same constant-time-compare
pattern as ``capsize_auth.tokens.opaque.matches``
(:mod:`hub_api.auth.signatures`).

Request contract, matched exactly by the sandbox runner in the sibling
``spikeforge`` repo (issue #48):

``POST /internal/v1/verifications/{version_id}``
    Header ``X-Verification-Signature``: lowercase hex HMAC-SHA256 of the
    raw request body, keyed with the shared ``verification_secret``.
    JSON body: ``{"passed": bool, "reasons": [str, ...], ...}``, where
    ``reasons`` is required non-empty when ``passed`` is false and any
    other field (NIR/compat/energy summary) is carried through verbatim.
"""

import uuid
from typing import Any

from fastapi import APIRouter, Request
from pydantic import ValidationError

from hub_api.auth.signatures import matches
from hub_api.deps import ConfigDep, SessionDep
from hub_api.errors import ServiceUnavailableError, UnauthorizedError
from hub_api.schemas.verifications import VerificationReport
from hub_api.uploads.verify import InvalidReportError, apply_report

router = APIRouter(prefix="/internal/v1/verifications")

#: Header carrying the hex HMAC-SHA256 of the raw request body.
SIGNATURE_HEADER = "X-Verification-Signature"


@router.post("/{version_id}")
async def receive_report(
    version_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    config: ConfigDep,
) -> dict[str, Any]:
    """Apply a signed verification report to one version."""
    body = await request.body()
    _authenticate(config, request, body)
    report = _parse(body)
    updated = await apply_report(session, version_id, report.model_dump())
    await session.commit()
    return {
        "version_id": str(updated.id),
        "state": updated.state,
        "published_at": (
            updated.published_at.isoformat()
            if updated.published_at
            else None
        ),
    }


def _authenticate(
    config: ConfigDep, request: Request, body: bytes
) -> None:
    """Refuse a callback that cannot prove it holds the shared secret.

    Mirrors ``token_secret``: an empty ``verification_secret`` has no
    development fallback, because a fallback secret that reaches
    production is indistinguishable from no secret at all.
    """
    if not config.verification_secret:
        raise ServiceUnavailableError(
            "no verification_secret is configured on this deployment"
        )
    presented = request.headers.get(SIGNATURE_HEADER)
    if not presented:
        raise UnauthorizedError(f"missing the {SIGNATURE_HEADER} header")
    if not matches(config.verification_secret, body, presented):
        raise UnauthorizedError("the callback signature does not match")


def _parse(body: bytes) -> VerificationReport:
    """Return the validated report, or explain why the body is unusable."""
    try:
        return VerificationReport.model_validate_json(body)
    except ValidationError as error:
        raise InvalidReportError(
            f"the verification report is malformed: {error}"
        ) from error
