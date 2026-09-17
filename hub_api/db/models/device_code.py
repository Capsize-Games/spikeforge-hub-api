"""A device-authorization grant awaiting approval."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow

#: Where an attempt has got to.
PENDING = "pending"
APPROVED = "approved"
DENIED = "denied"


class DeviceCode(Base):
    """One device-flow attempt: a code the app polls, and one a person types.

    The fallback for the case where handing off to a loopback listener cannot
    work -- a remote session, a machine with no browser handler, a locked-down
    desktop. The app shows ``user_code``; the person enters it on the website.
    """

    __tablename__ = "device_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    #: Hash of the long secret the application polls with.
    device_code_hash: Mapped[str] = mapped_column(
        sa.String(64), unique=True, index=True
    )
    #: The short code a person reads off a screen and types. Short enough to
    #: transcribe, so it is rate-limited and short-lived rather than strong.
    user_code: Mapped[str] = mapped_column(
        sa.String(16), unique=True, index=True
    )
    client_id: Mapped[str] = mapped_column(sa.String(64))
    scopes: Mapped[str] = mapped_column(sa.String(255), default="")
    state: Mapped[str] = mapped_column(sa.String(16), default=PENDING)
    #: Set once a signed-in person approves this attempt.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE")
    )
    #: Minimum seconds between polls; raised when a client polls too fast.
    interval_seconds: Mapped[int] = mapped_column(default=5)
    last_polled_at: Mapped[datetime | None] = mapped_column(Timestamp)
    #: Set when the tokens have been collected, so the grant is single-use.
    redeemed_at: Mapped[datetime | None] = mapped_column(Timestamp)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
