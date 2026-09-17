"""A browser sign-in."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow


class Session(Base):
    """A server-side web session addressed by an opaque cookie value.

    Deliberately not a signed token: sign-out and account deletion have to
    revoke a session immediately, and a stateful row does that without a
    revocation list to maintain.
    """

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    #: sha256 of the cookie value. The plaintext exists only in the cookie.
    token_hash: Mapped[str] = mapped_column(
        sa.String(64), unique=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    user_agent: Mapped[str] = mapped_column(sa.String(255), default="")
    #: Truncated hash, not the address: enough to spot a session moving hosts,
    #: not a stored identifier for the person behind it.
    ip_hash: Mapped[str] = mapped_column(sa.String(32), default="")
