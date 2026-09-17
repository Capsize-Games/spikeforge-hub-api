"""Reclaim what abandoned uploads left behind.

Correctness does not depend on this running: an expired reservation already
stops counting against an allowance, because pending bytes are derived from
reservations that have not expired. What it reclaims is *disk* -- the staged
file of a transfer that was interrupted -- and the rows that would otherwise
accumulate.
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.db.base import utcnow
from hub_api.db.models.model_version import RESERVED, ModelVersion
from hub_api.storage.base import Storage


async def sweep(session: AsyncSession, storage: Storage) -> int:
    """Delete expired reservations and their staged bytes.

    Returns how many were reclaimed, so a scheduled run can be logged with a
    number rather than a reassurance.
    """
    expired = await session.scalars(
        sa.select(ModelVersion).where(
            ModelVersion.state == RESERVED,
            ModelVersion.expires_at <= utcnow(),
        )
    )
    reclaimed = 0
    for version in expired:
        await storage.discard(str(version.id))
        await session.delete(version)
        reclaimed += 1
    await session.flush()
    return reclaimed
