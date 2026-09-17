"""A published model's identity and metadata."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow

#: Moderation states. ``hidden`` is the owner's choice, ``takedown`` is ours.
ACTIVE = "active"
HIDDEN = "hidden"
TAKEDOWN = "takedown"

PUBLIC = "public"
PRIVATE = "private"


class HubModel(Base):
    """A named model in one account's namespace, holding many versions.

    Named ``HubModel`` rather than ``Model`` so it cannot be confused with a
    trained artifact or with SQLAlchemy's own vocabulary; the table is
    ``models``.

    The licence fields mirror the toolkit's catalog schema deliberately, so a
    community entry and a curated one carry the same declarations: ``license``
    covers the weights, ``dataset_license`` covers the data they encode, and
    the two have different holders and different terms.
    """

    __tablename__ = "models"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    slug: Mapped[str] = mapped_column(sa.String(64))
    visibility: Mapped[str] = mapped_column(sa.String(16), default=PUBLIC)
    state: Mapped[str] = mapped_column(sa.String(16), default=ACTIVE)
    #: SPDX-style identifier, or the explicit ``unverified-candidate``
    #: marker. Free text is refused: see hub_api.catalog.licenses.
    license: Mapped[str] = mapped_column(sa.String(64))
    dataset: Mapped[str] = mapped_column(sa.String(64), default="")
    dataset_license: Mapped[str] = mapped_column(sa.String(64), default="")
    dataset_attribution: Mapped[str] = mapped_column(sa.Text, default="")
    summary: Mapped[str] = mapped_column(sa.String(200), default="")
    description: Mapped[str] = mapped_column(sa.Text, default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)

    __table_args__ = (
        sa.UniqueConstraint("owner_id", "slug", name="uq_model_owner_slug"),
    )
