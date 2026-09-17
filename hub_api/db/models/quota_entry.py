"""One movement in an account's storage ledger."""

import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from hub_api.db.base import Base, Timestamp, utcnow

#: Why a movement happened. Note there is no ``reserve`` reason: see the
#: class docstring.
COMMIT = "commit"
DELETE = "delete"
ADMIN_ADJUST = "admin_adjust"


class QuotaEntry(Base):
    """An append-only movement of bytes against one account's allowance.

    Deliberately a ledger rather than a ``bytes_used`` counter on the account.
    A counter drifts the first time a commit races a delete, and then a user
    is refused an upload with no way to find out why. A ledger can be
    recomputed from the stored artifacts and reconciled; a counter cannot be
    audited.

    Rows are never updated or deleted. A mistake is corrected by appending
    its inverse.

    The ledger records only bytes that are *actually stored*. A reservation is
    not a ledger row: it is the ``reserved`` model-version row itself, which
    already carries the size and an expiry. Deriving pending bytes from those
    rows means an abandoned upload stops counting against an allowance the
    moment it expires, with no compensating entry to write and no window in
    which a crashed request leaves a permanent charge behind.
    """

    __tablename__ = "quota_entries"

    id: Mapped[uuid.UUID] = mapped_column(
        sa.Uuid, primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        sa.ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    model_version_id: Mapped[uuid.UUID | None] = mapped_column(sa.Uuid)
    #: Positive when bytes are claimed, negative when they are given back.
    delta_bytes: Mapped[int] = mapped_column(sa.BigInteger)
    reason: Mapped[str] = mapped_column(sa.String(16))
    created_at: Mapped[datetime] = mapped_column(Timestamp, default=utcnow)
