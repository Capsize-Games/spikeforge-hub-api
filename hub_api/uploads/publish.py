"""Phase three: hand a received artifact to verification, or publish it.

A version becomes visible in the index here and nowhere else. Which of the
two paths it takes is a deployment decision: with a verification plane
configured it waits for a report, and without one it is published carrying
the honest ``unchecked`` label rather than sitting invisible forever.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.model_version import (
    PUBLISHED,
    UPLOADED,
    VERIFYING,
    ModelVersion,
)
from hub_api.errors import ConflictError


async def publish(
    session: AsyncSession, version: ModelVersion, config: Settings
) -> ModelVersion:
    """Move a received version on to verification, or straight to published."""
    if version.state != UPLOADED:
        raise ConflictError(
            f"this version is {version.state}; only a received upload can "
            "be committed"
        )
    if config.require_verification:
        version.state = VERIFYING
    else:
        _publish_unchecked(version)
    await session.flush()
    return version


def _publish_unchecked(version: ModelVersion) -> None:
    """Publish with a report that says plainly nothing was checked."""
    version.state = PUBLISHED
    version.published_at = utcnow()
    version.verification = {
        "passed": None,
        "reason": "no verification plane is configured on this deployment, "
        "so this artifact carries no machine checks beyond its checksum",
    }
