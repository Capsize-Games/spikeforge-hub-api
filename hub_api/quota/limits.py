"""The per-account ceilings, checked before an upload is accepted.

Every refusal names the limit and the current value. A quota error that does
not say what the limit was is a support request rather than an answer.
"""

import uuid
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.model_version import ModelVersion
from hub_api.errors import QuotaExceededError


async def check_artifact_size(size_bytes: int, config: Settings) -> None:
    """Refuse an artifact larger than a single upload may be."""
    if size_bytes > config.max_artifact_bytes:
        raise QuotaExceededError(
            "this artifact is larger than a single upload may be",
            limit_bytes=config.max_artifact_bytes,
            requested_bytes=size_bytes,
        )


async def check_model_count(
    session: AsyncSession, user_id: uuid.UUID, config: Settings
) -> None:
    """Refuse a new model once the namespace is full."""
    count = await _count(
        session,
        sa.select(sa.func.count())
        .select_from(HubModel)
        .where(HubModel.owner_id == user_id),
    )
    if count >= config.max_models_per_user:
        raise QuotaExceededError(
            "this account already holds as many models as it may",
            limit=config.max_models_per_user,
            current=count,
        )


async def check_version_count(
    session: AsyncSession, model_id: uuid.UUID, config: Settings
) -> None:
    """Refuse a new version once a model's history is full."""
    count = await _count(
        session,
        sa.select(sa.func.count())
        .select_from(ModelVersion)
        .where(ModelVersion.model_id == model_id),
    )
    if count >= config.max_versions_per_model:
        raise QuotaExceededError(
            "this model already holds as many versions as it may",
            limit=config.max_versions_per_model,
            current=count,
        )


async def check_daily_uploads(
    session: AsyncSession, user_id: uuid.UUID, config: Settings
) -> None:
    """Refuse an upload once today's count is spent.

    Independent of bytes: a thousand tiny uploads is a pattern worth slowing
    down even when every one of them fits the storage allowance.
    """
    since = utcnow() - timedelta(days=1)
    count = await _count(
        session,
        sa.select(sa.func.count())
        .select_from(ModelVersion)
        .join(HubModel, HubModel.id == ModelVersion.model_id)
        .where(
            HubModel.owner_id == user_id,
            ModelVersion.created_at >= since,
        ),
    )
    if count >= config.max_uploads_per_day:
        raise QuotaExceededError(
            "this account has started as many uploads today as it may",
            limit=config.max_uploads_per_day,
            current=count,
        )


async def _count(
    session: AsyncSession, statement: sa.Select[tuple[int]]
) -> int:
    """Return a scalar count, treating None as zero."""
    return int(await session.scalar(statement) or 0)
