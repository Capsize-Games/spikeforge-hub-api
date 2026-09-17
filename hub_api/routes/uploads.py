"""The two-phase upload, as three calls.

The split is the point: ``POST /v1/uploads`` answers "will you accept this?"
from metadata alone, so a caller is refused before spending bandwidth. The
``PUT`` then carries the bytes, and the commit publishes what was measured.
"""

import uuid
from typing import Any

import sqlalchemy as sa
from fastapi import APIRouter, Request

from hub_api.db.models.hub_model import HubModel
from hub_api.db.models.model_version import ModelVersion
from hub_api.db.models.user import User
from hub_api.deps import ConfigDep, SessionDep, StorageDep, WriteUser
from hub_api.errors import ConflictError, NotFoundError
from hub_api.schemas.uploads import UploadIntent
from hub_api.uploads import publish, receive, reserve

router = APIRouter(prefix="/v1/uploads")

#: Bytes read from the socket at a time. Large enough that the per-chunk
#: thread hand-off is not the bottleneck, small enough that a chunk is never
#: a meaningful amount of memory.
CHUNK_BYTES = 256 * 1024


@router.post("")
async def create(
    body: UploadIntent,
    session: SessionDep,
    storage: StorageDep,
    config: ConfigDep,
    user: WriteUser,
) -> dict[str, Any]:
    """Reserve an upload slot, or refuse with the limit that stopped it."""
    slot = await reserve(
        session, storage, user, body.to_request(), config
    )
    await session.commit()
    return {
        "upload_id": str(slot.upload_id),
        "put_url": f"/v1/uploads/{slot.upload_id}/content",
        "expires_at": slot.expires_at_epoch,
        "size_bytes": slot.size_bytes,
    }


@router.put("/{upload_id}/content")
async def content(
    upload_id: uuid.UUID,
    request: Request,
    session: SessionDep,
    storage: StorageDep,
    user: WriteUser,
) -> dict[str, Any]:
    """Receive the reserved bytes, streaming them to storage."""
    _check_declared_length(request)
    version = await receive(
        session,
        storage,
        upload_id,
        user.id,
        request.stream(),
    )
    await session.commit()
    return {
        "upload_id": str(version.id),
        "state": version.state,
        "sha256": version.sha256,
        "size_bytes": version.size_bytes,
    }


def _check_declared_length(request: Request) -> None:
    """Refuse a body that does not declare its length.

    A chunked upload would be accepted and then cut off mid-stream by the
    size cap, which wastes the caller's bandwidth to tell them something the
    header could have.
    """
    if not request.headers.get("content-length"):
        raise ConflictError(
            "send Content-Length: the upload is checked against the size "
            "the reservation declared"
        )


@router.post("/{upload_id}/commit")
async def commit(
    upload_id: uuid.UUID,
    session: SessionDep,
    config: ConfigDep,
    user: WriteUser,
) -> dict[str, Any]:
    """Publish a received version, or send it for verification."""
    version = await _owned_version(session, upload_id, user)
    published = await publish(session, version, config)
    await session.commit()
    return {
        "upload_id": str(published.id),
        "state": published.state,
        "published_at": (
            published.published_at.isoformat()
            if published.published_at
            else None
        ),
    }


async def _owned_version(
    session: SessionDep, upload_id: uuid.UUID, user: User
) -> ModelVersion:
    """Return the caller's own version row, or 404."""
    found = await session.scalar(
        sa.select(ModelVersion)
        .join(HubModel, HubModel.id == ModelVersion.model_id)
        .where(ModelVersion.id == upload_id, HubModel.owner_id == user.id)
    )
    if found is None:
        raise NotFoundError("no such upload for this account")
    return found
