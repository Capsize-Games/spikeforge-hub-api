"""A single-use authorization code from the desktop sign-in flow."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow


class AuthCode(Base):
    """One authorization code awaiting exchange for tokens.

    Stored rather than signed. An authorization code must be redeemable
    *once*, and a self-contained signed code cannot enforce that without a
    record of what has already been spent -- at which point the record is the
    simpler half of the design.

    Only the code's hash is kept, so a database copy yields nothing
    redeemable.
    """

    __tablename__ = "auth_codes"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    code_hash: Mapped[str] = mapped_column(
        sa.String(64), unique=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE")
    )
    client_id: Mapped[str] = mapped_column(sa.String(64))
    redirect_uri: Mapped[str] = mapped_column(sa.String(512))
    #: The PKCE challenge the client committed to. Required, not optional: a
    #: public client that skipped it would be exchangeable by anyone who
    #: intercepted the code.
    code_challenge: Mapped[str] = mapped_column(sa.String(128))
    scopes: Mapped[str] = mapped_column(sa.String(255), default="")
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    #: Set on redemption. A second presentation is refused, and is worth
    #: treating as a leak rather than as a retry.
    used_at: Mapped[datetime | None] = mapped_column(Timestamp)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
