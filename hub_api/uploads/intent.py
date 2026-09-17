"""Phase one: check everything, then reserve, before any byte is accepted.

The order matters. Every refusal that can be decided from metadata is decided
here, so a caller learns their upload will not be accepted *before* spending
bandwidth on it -- and so the host's own limits are enforced ahead of the
transfer rather than discovered during it.
"""

import uuid
from dataclasses import dataclass
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.model_version import RESERVED, ModelVersion
from hub_api.db.models.user import User
from hub_api.errors import ConflictError, ForbiddenError, QuotaExceededError
from hub_api.quota import usage_for
from hub_api.quota.footprint import check_footprint, check_free_space
from hub_api.quota.limits import (
    check_artifact_size,
    check_daily_uploads,
    check_model_count,
    check_version_count,
)
from hub_api.storage.base import Storage
from hub_api.storage.keys import is_sha256


@dataclass(frozen=True)
class Reservation:
    """A granted upload slot."""

    upload_id: uuid.UUID
    model_id: uuid.UUID
    expires_at_epoch: int
    size_bytes: int


@dataclass(frozen=True)
class UploadRequest:
    """What a caller asks for before sending bytes."""

    slug: str
    version: str
    sha256: str
    size_bytes: int
    license: str
    dataset: str = ""
    dataset_license: str = ""
    dataset_attribution: str = ""
    summary: str = ""


def _check_publisher(user: User, config: Settings) -> None:
    """Refuse an account that may not publish."""
    if not user.email_verified:
        raise ForbiddenError(
            "verify your email address before publishing: an unproven "
            "address cannot receive the correspondence publishing implies"
        )
    if config.publishing_gate == "open" or user.can_publish:
        return
    raise ForbiddenError(
        "publishing is invite-only on this deployment while moderation "
        "capacity is limited; browsing and downloading are unaffected"
    )


async def reserve(
    session: AsyncSession,
    storage: Storage,
    user: User,
    request: UploadRequest,
    config: Settings,
) -> Reservation:
    """Run every pre-transfer check and return a reservation."""
    _check_publisher(user, config)
    if not is_sha256(request.sha256):
        raise ConflictError("sha256 must be a lowercase hex digest")
    await check_artifact_size(request.size_bytes, config)
    await check_daily_uploads(session, user.id, config)
    await _check_allowance(session, user, request.size_bytes)
    await check_footprint(session, request.size_bytes, config)
    await check_free_space(storage, request.size_bytes, config)
    model = await _model_for(session, user, request, config)
    await check_version_count(session, model.id, config)
    return await _open_slot(session, model, request, config)


async def _check_allowance(
    session: AsyncSession, user: User, size_bytes: int
) -> None:
    """Refuse an upload the account has no room for."""
    usage = await usage_for(session, user.id, user.storage_limit)
    if usage.can_fit(size_bytes):
        return
    raise QuotaExceededError(
        "this upload does not fit in the account's storage allowance",
        limit_bytes=usage.limit_bytes,
        used_bytes=usage.used_bytes,
        reserved_bytes=usage.reserved_bytes,
        available_bytes=usage.available_bytes,
        requested_bytes=size_bytes,
    )


async def _model_for(
    session: AsyncSession,
    user: User,
    request: UploadRequest,
    config: Settings,
) -> HubModel:
    """Return the named model, creating it on first publish."""
    found = await session.scalar(
        sa.select(HubModel).where(
            HubModel.owner_id == user.id, HubModel.slug == request.slug
        )
    )
    if found is not None:
        return found
    await check_model_count(session, user.id, config)
    created = HubModel(
        owner_id=user.id,
        slug=request.slug,
        license=request.license,
        dataset=request.dataset,
        dataset_license=request.dataset_license,
        dataset_attribution=request.dataset_attribution,
        summary=request.summary,
    )
    session.add(created)
    await session.flush()
    return created


async def _open_slot(
    session: AsyncSession,
    model: HubModel,
    request: UploadRequest,
    config: Settings,
) -> Reservation:
    """Create the reserved version row that holds the allowance."""
    clash = await session.scalar(
        sa.select(ModelVersion.id).where(
            ModelVersion.model_id == model.id,
            ModelVersion.version == request.version,
        )
    )
    if clash is not None:
        raise ConflictError(
            f"version {request.version!r} already exists; versions are "
            "immutable, so publish a new one instead"
        )
    expires = utcnow() + timedelta(seconds=config.reservation_ttl_seconds)
    version = ModelVersion(
        model_id=model.id,
        version=request.version,
        sha256=request.sha256,
        size_bytes=request.size_bytes,
        state=RESERVED,
        expires_at=expires,
    )
    session.add(version)
    await session.flush()
    return Reservation(
        upload_id=version.id,
        model_id=model.id,
        expires_at_epoch=int(expires.timestamp()),
        size_bytes=request.size_bytes,
    )
