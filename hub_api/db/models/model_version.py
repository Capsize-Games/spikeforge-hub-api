"""One immutable version of a model."""

import uuid
from datetime import datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, JsonColumn, Timestamp, utcnow

#: Lifecycle. A row is created as ``reserved`` *before* any byte is accepted,
#: which is what makes the quota check happen ahead of the transfer rather
#: than after it.
RESERVED = "reserved"
UPLOADED = "uploaded"
VERIFYING = "verifying"
PUBLISHED = "published"
REJECTED = "rejected"
DELETED = "deleted"

#: States whose bytes are on disk and therefore count against a quota.
STORED = (UPLOADED, VERIFYING, PUBLISHED, REJECTED)


class ModelVersion(Base):
    """A single uploaded artifact, addressed by its own digest.

    Versions are immutable: republishing means a new version. That is what
    makes a pinned checksum worth anything, and it is the same property the
    curated catalog already relies on.

    ``manifest`` and ``verification`` are only ever written from bytes this
    service has read itself. A client's claims about accuracy or topology do
    not get stored here and then rendered as facts.
    """

    __tablename__ = "model_versions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    model_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("models.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(sa.String(64))
    #: Claimed at reservation, replaced by the digest this service computed
    #: while the bytes arrived.
    sha256: Mapped[str] = mapped_column(sa.String(64), index=True)
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    object_key: Mapped[str] = mapped_column(sa.String(128), default="")
    state: Mapped[str] = mapped_column(sa.String(16), default=RESERVED)
    manifest: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn)
    verification: Mapped[dict[str, Any] | None] = mapped_column(JsonColumn)
    download_count: Mapped[int] = mapped_column(sa.BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    published_at: Mapped[datetime | None] = mapped_column(Timestamp)
    #: When a ``reserved`` row stops holding its quota. A janitor releases it
    #: and deletes the staged bytes, so an abandoned upload cannot pin an
    #: allowance permanently.
    expires_at: Mapped[datetime | None] = mapped_column(Timestamp)

    __table_args__ = (
        sa.UniqueConstraint(
            "model_id", "version", name="uq_version_model_version"
        ),
    )
