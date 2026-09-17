"""Shared support for the hub's own OAuth grants.

Used by both :mod:`hub_api.auth.grants` (loopback PKCE, RFC 8252) and
:mod:`hub_api.auth.device_codes` (the device-flow fallback, RFC 8628): scope
parsing, and resolving the account behind a redeemed grant.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.auth import credentials
from hub_api.db.base import utcnow
from hub_api.db.models.user import ACTIVE, User
from hub_api.errors import InvalidRequestError, UnauthorizedError


def expiry(ttl_seconds: int) -> datetime:
    """Return the timestamp ``ttl_seconds`` from now."""
    return utcnow() + timedelta(seconds=ttl_seconds)


def check_known_scopes(scopes: list[str]) -> None:
    """Refuse a scope this service does not define."""
    unknown = sorted(set(scopes) - set(credentials.ALL_SCOPES))
    if unknown:
        raise InvalidRequestError(f"unknown scopes: {', '.join(unknown)}")


def parse_scope(raw: str) -> str:
    """Return ``raw`` validated and normalised for storage."""
    requested = raw.split()
    check_known_scopes(requested)
    return " ".join(requested)


def scopes_of(stored: str) -> list[str]:
    """Return the scopes a grant carries, or every scope when none named."""
    requested = stored.split()
    return requested or list(credentials.ALL_SCOPES)


async def active_owner(
    session: AsyncSession, user_id: uuid.UUID | None
) -> User:
    """Return the account behind a redeemed grant, or refuse it."""
    user = await session.get(User, user_id) if user_id else None
    if user is None or user.state != ACTIVE:
        raise UnauthorizedError("the account for this grant is not active")
    return user
