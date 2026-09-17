"""Web sessions, addressed by an opaque cookie value.

Not a signed token. Sign-out, a password change, and account deletion all have
to revoke a session *now*, and a row that can be deleted does that without a
blocklist to maintain and consult on every request.

Both expiries are enforced: an absolute one so a session cannot live forever,
and an idle one so an abandoned browser stops being a way in.
"""

import uuid
from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.session import Session
from hub_api.db.models.user import ACTIVE, User
from hub_api.tokens import hash_token, new_token


async def start(
    session: AsyncSession,
    user: User,
    config: Settings,
    user_agent: str = "",
    ip_hash: str = "",
) -> str:
    """Create a session for ``user`` and return the cookie value."""
    token = new_token(prefix="sfh_s_")
    session.add(
        Session(
            token_hash=token.hashed,
            user_id=user.id,
            expires_at=utcnow()
            + timedelta(seconds=config.session_absolute_ttl_seconds),
            user_agent=user_agent[:255],
            ip_hash=ip_hash[:32],
        )
    )
    await session.flush()
    return token.plaintext


async def resolve(
    session: AsyncSession, cookie: str, config: Settings
) -> User | None:
    """Return the signed-in account for ``cookie``, or None.

    Touches ``last_seen_at`` so the idle window tracks use rather than
    sign-in time.
    """
    row = await session.scalar(
        sa.select(Session).where(Session.token_hash == hash_token(cookie))
    )
    if row is None or not _live(row, config):
        return None
    user = await session.get(User, row.user_id)
    if user is None or user.state != ACTIVE:
        return None
    row.last_seen_at = utcnow()
    await session.flush()
    return user


def _live(row: Session, config: Settings) -> bool:
    """Return whether a session row is still usable."""
    now = utcnow()
    if row.revoked_at is not None or row.expires_at <= now:
        return False
    idle_limit = timedelta(seconds=config.session_idle_ttl_seconds)
    return row.last_seen_at + idle_limit > now


async def revoke(session: AsyncSession, cookie: str) -> None:
    """Revoke the session identified by ``cookie``, if it exists."""
    row = await session.scalar(
        sa.select(Session).where(Session.token_hash == hash_token(cookie))
    )
    if row is not None:
        row.revoked_at = utcnow()
        await session.flush()


async def revoke_all(session: AsyncSession, user_id: uuid.UUID) -> int:
    """Revoke every live session for an account, returning the count."""
    rows = await session.scalars(
        sa.select(Session).where(
            Session.user_id == user_id, Session.revoked_at.is_(None)
        )
    )
    revoked = 0
    for row in rows:
        row.revoked_at = utcnow()
        revoked += 1
    await session.flush()
    return revoked
