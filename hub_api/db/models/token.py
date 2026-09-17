"""An API credential."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, JsonColumn, Timestamp, utcnow

#: Token kinds. Access and refresh tokens belong to an OAuth grant; a personal
#: access token is minted by the user and is the only kind they ever see twice.
ACCESS = "access"
REFRESH = "refresh"
PAT = "pat"


class Token(Base):
    """A hashed bearer credential with a scope set and a lifetime.

    Only the sha256 of the value is stored. These are high-entropy random
    strings rather than passwords, so a slow key-derivation function would buy
    nothing; what matters is that a database copy contains no usable
    credential.
    """

    __tablename__ = "tokens"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    token_hash: Mapped[str] = mapped_column(
        sa.String(64), unique=True, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(sa.String(16))
    name: Mapped[str] = mapped_column(sa.String(120), default="")
    scopes: Mapped[list[str]] = mapped_column(JsonColumn, default=list)
    #: Groups a refresh token with its successors: presenting a rotated
    #: refresh token invalidates the whole chain rather than just itself.
    chain_id: Mapped[uuid.UUID] = mapped_column(sa.Uuid, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(Timestamp)
    revoked_at: Mapped[datetime | None] = mapped_column(Timestamp)
    last_used_at: Mapped[datetime | None] = mapped_column(Timestamp)
