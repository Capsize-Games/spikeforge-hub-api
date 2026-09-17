"""A provider account linked to a hub account."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow


class Identity(Base):
    """One external provider account, linked to one hub account.

    A row per link rather than a column per provider. The library this was
    built on took the other approach -- ``google_id``, ``twitch_id``,
    ``steam_id`` -- which means a schema migration every time a deployment
    wants to offer one more provider, and no way to hold two accounts from
    the same provider.

    ``subject`` is the provider's own immutable identifier, never the email
    address: people change those, and some providers let them be reassigned.
    """

    __tablename__ = "identities"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str] = mapped_column(sa.String(32))
    subject: Mapped[str] = mapped_column(sa.String(128))
    #: What the provider reported at link time, kept for display and for
    #: noticing that it has since changed. Not used for matching.
    email: Mapped[str] = mapped_column(sa.String(320), default="")
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(Timestamp)

    __table_args__ = (
        sa.UniqueConstraint(
            "provider", "subject", name="uq_identity_provider_subject"
        ),
    )
