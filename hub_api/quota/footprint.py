"""The two limits that protect the host rather than the user.

The service shares its filesystem with another project's growing media
library. A hub that fills that volume takes the neighbour down with it, so
this is enforced structurally at upload time and not merely monitored:

* a **footprint cap** -- the share of the volume this service may ever claim,
  independent of how many accounts exist or what their allowances add up to;
* a **free-space floor** -- a level below which uploads stop regardless of the
  cap, so a mistaken cap or a neighbour's growth spurt still cannot produce a
  full filesystem.

Per-account allowances are deliberately allowed to oversubscribe the cap:
they exist for fairness between users, and this exists to keep a promise to
the machine.
"""

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.models.quota_entry import QuotaEntry
from hub_api.errors import QuotaExceededError, ServiceUnavailableError
from hub_api.storage.base import Storage


async def total_stored_bytes(session: AsyncSession) -> int:
    """Return the ledger balance across every account."""
    total = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(QuotaEntry.delta_bytes), 0))
    )
    return int(total or 0)


async def check_footprint(
    session: AsyncSession, size_bytes: int, config: Settings
) -> None:
    """Refuse an upload that would take the service past its own cap."""
    total = await total_stored_bytes(session)
    if total + size_bytes > config.footprint_cap_bytes:
        raise QuotaExceededError(
            "the hub has reached the total storage it may use on this host; "
            "this is a service-wide limit, not this account's allowance",
            limit_bytes=config.footprint_cap_bytes,
            stored_bytes=total,
        )


async def check_free_space(
    storage: Storage, size_bytes: int, config: Settings
) -> None:
    """Refuse an upload that would leave the volume below its floor."""
    free = await storage.free_bytes()
    if free - size_bytes < config.volume_free_floor_bytes:
        raise ServiceUnavailableError(
            "there is not enough free space on the artifact volume to "
            "accept an upload right now",
            free_bytes=free,
            floor_bytes=config.volume_free_floor_bytes,
        )
