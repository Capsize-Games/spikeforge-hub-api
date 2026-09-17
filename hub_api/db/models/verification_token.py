"""A single-use, hashed token proving something about one account.

One table for two purposes -- proving control of an address, and
authorizing a password reset -- because both are the same shape: an opaque
secret, stored only as a hash, tied to one account, good for one redemption
before its expiry. That mirrors how
:class:`~hub_api.db.models.token.Token` uses ``kind`` for access, refresh,
and personal-access tokens rather than a table per kind.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow

#: What a token authorizes.
EMAIL_VERIFICATION = "email_verification"
PASSWORD_RESET = "password_reset"


class VerificationToken(Base):
    """A hashed, single-use token tied to one account and one purpose.

    Only the sha256 of the value is stored, so a database copy is not a
    usable verification or reset link -- the same reasoning behind
    :class:`~hub_api.db.models.session.Session` and
    :class:`~hub_api.db.models.token.Token`.
    """

    __tablename__ = "verification_tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(
        sa.String(64), unique=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    purpose: Mapped[str] = mapped_column(sa.String(32))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(Timestamp)
    #: Null until redeemed. Set exactly once: a second redemption attempt
    #: finds this already filled in and is refused.
    used_at: Mapped[datetime | None] = mapped_column(Timestamp)
