"""Phase two: take the bytes, and believe only what was measured.

The client told us a digest and a size at reservation time. Those were
assertions. What is stored is checked against them here, from bytes this
service hashed itself as they arrived -- so a caller cannot reserve two
megabytes and store two hundred, and cannot claim someone else's checksum for
their own content.
"""

import uuid
from collections.abc import AsyncIterator

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.db.base import utcnow
from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.model_version import (
    RESERVED,
    UPLOADED,
    ModelVersion,
)
from hub_api.db.models.quota_entry import COMMIT, QuotaEntry
from hub_api.errors import (
    ConflictError,
    NotFoundError,
    UnprocessableUploadError,
)
from hub_api.storage.base import Storage
from hub_api.storage.blob import StoredBlob


async def _reserved_slot(
    session: AsyncSession, upload_id: uuid.UUID, user_id: uuid.UUID
) -> ModelVersion:
    """Return the caller's live reservation, or explain why there is none."""
    version = await session.scalar(
        sa.select(ModelVersion)
        .join(HubModel, HubModel.id == ModelVersion.model_id)
        .where(ModelVersion.id == upload_id, HubModel.owner_id == user_id)
    )
    if version is None:
        raise NotFoundError("no such upload for this account")
    if version.state != RESERVED:
        raise ConflictError(
            f"this upload is {version.state}, not awaiting bytes"
        )
    if version.expires_at is not None and version.expires_at <= utcnow():
        raise ConflictError(
            "the reservation expired; start a new upload. Reservations are "
            "short-lived so an abandoned one cannot hold an allowance"
        )
    return version


def _check_measured(version: ModelVersion, blob: StoredBlob) -> None:
    """Refuse bytes that are not what the reservation described."""
    if blob.size_bytes != version.size_bytes:
        raise UnprocessableUploadError(
            "the uploaded byte count does not match the reservation",
            reserved_bytes=version.size_bytes,
            received_bytes=blob.size_bytes,
        )
    if blob.sha256 != version.sha256:
        raise UnprocessableUploadError(
            "the uploaded bytes do not have the digest the reservation "
            "declared",
            declared_sha256=version.sha256,
            received_sha256=blob.sha256,
        )


async def receive(
    session: AsyncSession,
    storage: Storage,
    upload_id: uuid.UUID,
    user_id: uuid.UUID,
    chunks: AsyncIterator[bytes],
) -> ModelVersion:
    """Stream ``chunks`` into storage against a live reservation."""
    version = await _reserved_slot(session, upload_id, user_id)
    blob = await storage.stage(
        str(upload_id), chunks, max_bytes=version.size_bytes
    )
    try:
        _check_measured(version, blob)
    except UnprocessableUploadError:
        await storage.discard(str(upload_id))
        await _abandon(session, version)
        raise
    version.object_key = await storage.promote(str(upload_id), blob.sha256)
    version.state = UPLOADED
    session.add(
        QuotaEntry(
            user_id=user_id,
            model_version_id=version.id,
            delta_bytes=blob.size_bytes,
            reason=COMMIT,
        )
    )
    await session.flush()
    return version


async def _abandon(session: AsyncSession, version: ModelVersion) -> None:
    """Drop a reservation whose bytes were refused.

    Deleting the row rather than marking it failed frees the version name, so
    a caller who mis-declared a digest can simply retry with the same name.
    """
    await session.delete(version)
    await session.flush()
