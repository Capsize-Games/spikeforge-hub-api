"""Bearer credentials: access tokens, refresh tokens, and PATs.

All three are opaque and stored only as a hash, so a database copy contains
nothing usable. That is a deliberate departure from the signed-JWT approach
the underlying library also offers: this service needs a PAT to be revocable
the moment someone pastes one into a public repository, and a stateless token
cannot be.

Refresh tokens rotate. Presenting one that has already been exchanged
invalidates its whole chain, because the only ways that happens are a stolen
token being replayed and a client bug -- and both are better answered by
ending the session than by issuing more credentials.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.token import ACCESS, PAT, REFRESH, Token
from hub_api.db.models.user import ACTIVE, User
from hub_api.errors import UnauthorizedError
from hub_api.tokens import hash_token, new_token

#: What a credential is allowed to do.
READ = "models:read"
WRITE = "models:write"
ALL_SCOPES = (READ, WRITE)

_PREFIXES = {ACCESS: "sfh_at_", REFRESH: "sfh_rt_", PAT: "sfh_pat_"}


@dataclass(frozen=True)
class IssuedPair:
    """A freshly issued access and refresh token."""

    access_token: str
    refresh_token: str
    expires_in: int
    scopes: list[str]


def _ttl_for(kind: str, config: Settings) -> int | None:
    """Return the lifetime in seconds for ``kind``, or None for no expiry."""
    if kind == ACCESS:
        return config.access_token_ttl_seconds
    if kind == REFRESH:
        return config.refresh_token_ttl_seconds
    return None


@dataclass(frozen=True)
class _Mint:
    """What one token row needs, grouped to keep the minting call short."""

    user_id: uuid.UUID
    kind: str
    scopes: list[str]
    chain_id: uuid.UUID | None = None
    name: str = ""


async def _mint(
    session: AsyncSession, spec: _Mint, config: Settings
) -> str:
    """Create a token row and return its one-time plaintext."""
    token = new_token(prefix=_PREFIXES[spec.kind])
    session.add(
        Token(
            token_hash=token.hashed,
            user_id=spec.user_id,
            kind=spec.kind,
            name=spec.name,
            scopes=spec.scopes,
            chain_id=spec.chain_id or uuid.uuid4(),
            expires_at=_expiry(_ttl_for(spec.kind, config)),
        )
    )
    await session.flush()
    return token.plaintext


def _expiry(ttl: int | None) -> datetime | None:
    """Return when a token with lifetime ``ttl`` stops working."""
    return utcnow() + timedelta(seconds=ttl) if ttl else None


async def issue_pair(
    session: AsyncSession,
    user: User,
    scopes: list[str],
    config: Settings,
    chain_id: uuid.UUID | None = None,
) -> IssuedPair:
    """Issue an access/refresh pair for ``user``."""
    chain = chain_id or uuid.uuid4()
    access = await _mint(
        session, _Mint(user.id, ACCESS, scopes, chain), config
    )
    refresh = await _mint(
        session, _Mint(user.id, REFRESH, scopes, chain), config
    )
    return IssuedPair(
        access_token=access,
        refresh_token=refresh,
        expires_in=config.access_token_ttl_seconds,
        scopes=scopes,
    )


async def issue_pat(
    session: AsyncSession,
    user: User,
    scopes: list[str],
    name: str,
    config: Settings,
) -> str:
    """Issue a personal access token and return its plaintext once."""
    return await _mint(
        session, _Mint(user.id, PAT, scopes, name=name), config
    )


async def resolve(
    session: AsyncSession, presented: str
) -> tuple[User, Token]:
    """Return the account and token row behind a credential."""
    row = await session.scalar(
        sa.select(Token).where(Token.token_hash == hash_token(presented))
    )
    if row is None or row.kind == REFRESH:
        raise UnauthorizedError("the credential presented is not usable")
    _check_live(row)
    user = await _active_owner(session, row)
    row.last_used_at = utcnow()
    await session.flush()
    return user, row


def _check_live(row: Token) -> None:
    """Refuse a revoked or expired token."""
    if row.revoked_at is not None:
        raise UnauthorizedError("this credential has been revoked")
    if row.expires_at is not None and row.expires_at <= utcnow():
        raise UnauthorizedError("this credential has expired")


async def rotate(
    session: AsyncSession, presented: str, config: Settings
) -> IssuedPair:
    """Exchange a refresh token for a new pair, invalidating the old one."""
    row = await session.scalar(
        sa.select(Token).where(
            Token.token_hash == hash_token(presented),
            Token.kind == REFRESH,
        )
    )
    if row is None:
        raise UnauthorizedError("no such refresh token")
    await _check_not_replayed(session, row)
    _check_live(row)
    user = await _active_owner(session, row)
    row.revoked_at = utcnow()
    return await issue_pair(
        session, user, list(row.scopes), config, chain_id=row.chain_id
    )


async def _check_not_replayed(
    session: AsyncSession, row: Token
) -> None:
    """End the whole grant if an already-exchanged token comes back.

    The only ways that happens are a stolen token being replayed and a
    client bug, and both are better answered by ending the session than by
    issuing more credentials.
    """
    if row.revoked_at is None:
        return
    await _break_chain(session, row.chain_id)
    raise UnauthorizedError(
        "this refresh token was already exchanged; the session has been "
        "ended because a replayed refresh token means it may be in "
        "someone else's hands"
    )


async def _active_owner(session: AsyncSession, row: Token) -> User:
    """Return the token's account, refusing one that is not active."""
    user = await session.get(User, row.user_id)
    if user is None or user.state != ACTIVE:
        raise UnauthorizedError(
            "the account for this credential is not active"
        )
    return user


async def _break_chain(
    session: AsyncSession, chain_id: uuid.UUID
) -> None:
    """Revoke every credential descended from one grant."""
    rows = await session.scalars(
        sa.select(Token).where(
            Token.chain_id == chain_id, Token.revoked_at.is_(None)
        )
    )
    for row in rows:
        row.revoked_at = utcnow()
    await session.flush()
