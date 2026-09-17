"""What an account has stored, and what it has in flight."""

import uuid
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.db.base import utcnow
from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.model_version import RESERVED, ModelVersion
from hub_api.db.models.quota_entry import QuotaEntry


@dataclass(frozen=True)
class Usage:
    """One account's storage position."""

    #: Bytes on disk, summed from the ledger.
    used_bytes: int
    #: Bytes promised to uploads that have been reserved but not committed.
    reserved_bytes: int
    limit_bytes: int

    @property
    def available_bytes(self) -> int:
        """Return what may still be reserved, never below zero."""
        return max(0, self.limit_bytes - self.used_bytes - self.reserved_bytes)

    def can_fit(self, size_bytes: int) -> bool:
        """Return whether ``size_bytes`` still fits in the allowance."""
        return size_bytes <= self.available_bytes


async def stored_bytes(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Return the ledger balance for ``user_id``."""
    total = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(QuotaEntry.delta_bytes), 0))
        .where(QuotaEntry.user_id == user_id)
    )
    return int(total or 0)


async def pending_bytes(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Return bytes held by this account's live reservations.

    An expired reservation is excluded here rather than waiting for the
    janitor, so a crashed upload frees the allowance on its own.
    """
    total = await session.scalar(
        sa.select(sa.func.coalesce(sa.func.sum(ModelVersion.size_bytes), 0))
        .join(HubModel, HubModel.id == ModelVersion.model_id)
        .where(
            HubModel.owner_id == user_id,
            ModelVersion.state == RESERVED,
            ModelVersion.expires_at > utcnow(),
        )
    )
    return int(total or 0)


async def usage_for(
    session: AsyncSession, user_id: uuid.UUID, limit_bytes: int
) -> Usage:
    """Return ``user_id``'s storage position against ``limit_bytes``."""
    return Usage(
        used_bytes=await stored_bytes(session, user_id),
        reserved_bytes=await pending_bytes(session, user_id),
        limit_bytes=limit_bytes,
    )
