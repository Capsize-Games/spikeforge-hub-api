"""Phase four: the sandbox's report lands, and a version leaves VERIFYING.

Nothing here runs a check itself -- this module never imports ``torch`` --
it only records the sandbox's already-made decision and moves the version
to where that decision belongs. See ``hub_api.routes.verifications`` for the
callback this is called from, and ``hub_api.catalog.trust.label_for`` for
the one field of the stored report anything else here reads back.
"""

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.db.base import utcnow
from hub_api.db.models.model_version import (
    PUBLISHED,
    REJECTED,
    VERIFYING,
    ModelVersion,
)
from hub_api.errors import ConflictError, HubError, NotFoundError


class InvalidReportError(HubError):
    """The report's shape cannot be trusted or acted on as given."""

    status = 422
    code = "invalid_verification_report"


async def apply_report(
    session: AsyncSession, version_id: uuid.UUID, report: dict[str, Any]
) -> ModelVersion:
    """Publish or reject the version ``report`` describes.

    The report is stored verbatim in ``version.verification`` either way.
    A failing report must carry at least one named reason: this is the
    line that makes "verification failed" impossible to store, because
    nothing downstream can invent a reason that was never given.
    """
    version = await _by_id(session, version_id)
    if version.state != VERIFYING:
        raise ConflictError(
            f"this version is {version.state}; only a version pending "
            "verification can receive a report"
        )
    passed = bool(report.get("passed"))
    if not passed and not report.get("reasons"):
        raise InvalidReportError(
            "a failing report must name at least one reason in "
            "'reasons'; 'verification failed' alone is not a reason"
        )
    version.verification = report
    if passed:
        version.state = PUBLISHED
        version.published_at = utcnow()
    else:
        version.state = REJECTED
    await session.flush()
    return version


async def _by_id(
    session: AsyncSession, version_id: uuid.UUID
) -> ModelVersion:
    """Return the version a report was posted for, or refuse."""
    found = await session.get(ModelVersion, version_id)
    if found is None:
        raise NotFoundError(f"no such version {version_id}")
    return found
