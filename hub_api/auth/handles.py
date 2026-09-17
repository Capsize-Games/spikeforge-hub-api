"""Choosing a handle for a new account.

A handle is public and appears in every artifact id the account publishes, so
it is derived from something the person recognises -- their provider username,
or the local part of their address -- rather than generated. When the obvious
choice is taken or reserved, a numeric suffix is added rather than asking a
person to invent a name during sign-up.
"""

import re

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.catalog.names import RESERVED_HANDLES
from hub_api.db.models.user import User

_DISALLOWED = re.compile(r"[^a-z0-9-]+")
_COLLAPSE = re.compile(r"-{2,}")
#: Leaves room for a suffix inside the 39-character limit.
_STEM_LIMIT = 30
_FALLBACK = "user"


def stem_from(*candidates: str) -> str:
    """Return a usable handle stem from the first workable candidate."""
    for candidate in candidates:
        cleaned = _clean(candidate)
        if cleaned:
            return cleaned
    return _FALLBACK


def _clean(raw: str) -> str:
    """Return ``raw`` reduced to handle-legal characters."""
    lowered = raw.strip().lower().split("@")[0]
    replaced = _DISALLOWED.sub("-", lowered)
    collapsed = _COLLAPSE.sub("-", replaced).strip("-")
    return collapsed[:_STEM_LIMIT]


async def allocate(session: AsyncSession, *candidates: str) -> str:
    """Return a free handle derived from ``candidates``.

    The suffix search is bounded. Running out is not something a person
    should be told to solve by trying again, so it falls back to a stem that
    cannot realistically collide.
    """
    stem = stem_from(*candidates)
    if await _is_free(session, stem):
        return stem
    for suffix in range(2, 1000):
        attempt = f"{stem}-{suffix}"
        if await _is_free(session, attempt):
            return attempt
    return f"{_FALLBACK}-{await _count(session) + 1}"


async def _is_free(session: AsyncSession, handle: str) -> bool:
    """Return whether ``handle`` may be allocated."""
    if handle in RESERVED_HANDLES:
        return False
    taken = await session.scalar(
        sa.select(User.id).where(User.handle == handle)
    )
    return taken is None


async def _count(session: AsyncSession) -> int:
    """Return how many accounts exist."""
    return int(
        await session.scalar(sa.select(sa.func.count()).select_from(User))
        or 0
    )
