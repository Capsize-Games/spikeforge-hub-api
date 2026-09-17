"""Reading the published community namespace."""

import sqlalchemy as sa
from sqlalchemy import Select
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.db.models.hub_model import ACTIVE, PUBLIC, HubModel
from hub_api.db.models.model_version import (
    PUBLISHED,
    REJECTED,
    ModelVersion,
)
from hub_api.db.models.user import User

#: One row of the public listing: the model, its version, and its owner.
PublishedRow = tuple[HubModel, ModelVersion, str]


def _published() -> Select[tuple[HubModel, ModelVersion, str]]:
    """Return the base query for publicly visible published versions."""
    return (
        sa.select(HubModel, ModelVersion, User.handle)
        .join(ModelVersion, ModelVersion.model_id == HubModel.id)
        .join(User, User.id == HubModel.owner_id)
        .where(
            HubModel.state == ACTIVE,
            HubModel.visibility == PUBLIC,
            ModelVersion.state == PUBLISHED,
        )
    )


async def published(
    session: AsyncSession,
    query: str = "",
    limit: int = 100,
) -> list[PublishedRow]:
    """Return published versions, newest first, optionally filtered."""
    statement = _published()
    if query:
        pattern = f"%{query.lower()}%"
        statement = statement.where(
            sa.or_(
                sa.func.lower(HubModel.slug).like(pattern),
                sa.func.lower(HubModel.summary).like(pattern),
                sa.func.lower(HubModel.dataset).like(pattern),
            )
        )
    statement = statement.order_by(
        ModelVersion.published_at.desc()
    ).limit(limit)
    rows = await session.execute(statement)
    return [(m, v, h) for m, v, h in rows.all()]


async def one_version(
    session: AsyncSession, handle: str, slug: str, version: str
) -> PublishedRow | None:
    """Return a single published version, or None."""
    found = await session.execute(
        _published().where(
            User.handle == handle,
            HubModel.slug == slug,
            ModelVersion.version == version,
        )
    )
    row = found.first()
    if row is None:
        return None
    return (row[0], row[1], row[2])


async def latest_version(
    session: AsyncSession, handle: str, slug: str
) -> PublishedRow | None:
    """Return a model's most recently published version, or None."""
    found = await session.execute(
        _published()
        .where(User.handle == handle, HubModel.slug == slug)
        .order_by(ModelVersion.published_at.desc())
        .limit(1)
    )
    row = found.first()
    if row is None:
        return None
    return (row[0], row[1], row[2])


async def latest_rejected(
    session: AsyncSession, handle: str, slug: str
) -> PublishedRow | None:
    """Return a model's most recently rejected version, or None.

    A rejected version never appears in :func:`published`, but its named
    reasons still have to be reachable by handle/slug: a rejection is not
    the same as a namespace nobody has used, and a bare 404 would hide the
    very reasons ``hub_api.uploads.verify`` requires a failing report to
    name.
    """
    found = await session.execute(
        sa.select(HubModel, ModelVersion, User.handle)
        .join(ModelVersion, ModelVersion.model_id == HubModel.id)
        .join(User, User.id == HubModel.owner_id)
        .where(
            HubModel.state == ACTIVE,
            HubModel.visibility == PUBLIC,
            User.handle == handle,
            HubModel.slug == slug,
            ModelVersion.state == REJECTED,
        )
        .order_by(ModelVersion.created_at.desc())
        .limit(1)
    )
    row = found.first()
    if row is None:
        return None
    return (row[0], row[1], row[2])
