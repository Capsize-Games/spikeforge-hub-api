"""An account."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow

#: Account lifecycle states. ``suspended`` blocks sign-in and publishing but
#: leaves published artifacts reachable; ``deleted`` is the tombstone left
#: after personal data has been removed.
ACTIVE = "active"
SUSPENDED = "suspended"
DELETED = "deleted"


class User(Base):
    """A person with a handle, a storage allowance, and a namespace.

    An account may have a password, one or more linked providers, or both --
    the providers live in :class:`~hub_api.db.models.identity.Identity` rather
    than as a column per provider, so enabling a new one is configuration and
    not a migration.

    ``handle`` is stored already lower-cased by the application rather than
    relying on a case-insensitive column type, so the unique index behaves the
    same on PostgreSQL and SQLite.
    """

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    handle: Mapped[str] = mapped_column(
        sa.String(39), unique=True, index=True
    )
    email: Mapped[str] = mapped_column(
        sa.String(320), unique=True, index=True
    )
    #: False until the address is proven. An unverified account may sign in
    #: and browse but may not publish: an unproven address cannot receive the
    #: takedown or licence correspondence publishing implies.
    email_verified: Mapped[bool] = mapped_column(default=False)
    #: Null for an account that only ever signed in through a provider.
    password_hash: Mapped[str | None] = mapped_column(sa.String(128))
    display_name: Mapped[str] = mapped_column(sa.String(120), default="")
    avatar_url: Mapped[str] = mapped_column(sa.String(512), default="")
    storage_limit: Mapped[int] = mapped_column(sa.BigInteger)
    #: Whether this account may publish, so the invite gate is per-account
    #: rather than a service-wide switch that has to be flipped for everyone.
    can_publish: Mapped[bool] = mapped_column(default=False)
    #: Incremented to invalidate every credential already issued -- what a
    #: password change and "sign out everywhere" do.
    token_version: Mapped[int] = mapped_column(default=0)
    state: Mapped[str] = mapped_column(sa.String(16), default=ACTIVE)
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
