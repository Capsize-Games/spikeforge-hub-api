"""Proving control of an address, and resetting a forgotten password.

Both are minted, redeemed, and expired the same way -- an opaque token,
hashed at rest, single-use, tied to one account -- so they share
:class:`~hub_api.db.models.verification_token.VerificationToken` rather
than each growing its own table. Emailing the token is layered on top of
minting it, so the token logic itself stays testable without an SMTP
transport.
"""

from datetime import timedelta

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.user import User
from hub_api.db.models.verification_token import (
    EMAIL_VERIFICATION,
    PASSWORD_RESET,
    VerificationToken,
)
from hub_api.email.base import EmailSender
from hub_api.errors import UnauthorizedError
from hub_api.tokens import hash_token, new_token

_PREFIXES = {EMAIL_VERIFICATION: "sfh_ev_", PASSWORD_RESET: "sfh_pr_"}


def _ttl_seconds(purpose: str, config: Settings) -> int:
    """Return the lifetime in seconds for a token of ``purpose``."""
    if purpose == EMAIL_VERIFICATION:
        return config.email_verification_ttl_seconds
    return config.password_reset_ttl_seconds


async def mint(
    session: AsyncSession, user: User, purpose: str, config: Settings
) -> str:
    """Create a token for ``purpose`` and return its one-time plaintext."""
    token = new_token(prefix=_PREFIXES[purpose])
    session.add(
        VerificationToken(
            token_hash=token.hashed,
            user_id=user.id,
            purpose=purpose,
            expires_at=utcnow()
            + timedelta(seconds=_ttl_seconds(purpose, config)),
        )
    )
    await session.flush()
    return token.plaintext


async def redeem(
    session: AsyncSession, presented: str, purpose: str
) -> User:
    """Redeem a single-use token, returning the account it names."""
    row = await session.scalar(
        sa.select(VerificationToken).where(
            VerificationToken.token_hash == hash_token(presented),
            VerificationToken.purpose == purpose,
        )
    )
    if row is None:
        raise UnauthorizedError("this link is invalid or has expired")
    _check_unused(row)
    user = await _owner(session, row)
    row.used_at = utcnow()
    await session.flush()
    return user


def _check_unused(row: VerificationToken) -> None:
    """Refuse a token that has already been redeemed, or has expired."""
    if row.used_at is not None:
        raise UnauthorizedError("this link has already been used")
    if row.expires_at <= utcnow():
        raise UnauthorizedError("this link is invalid or has expired")


async def _owner(session: AsyncSession, row: VerificationToken) -> User:
    """Return the account a token row belongs to, refusing a missing one."""
    user = await session.get(User, row.user_id)
    if user is None:
        raise UnauthorizedError("this link is no longer valid")
    return user


async def send_verification_email(
    session: AsyncSession, user: User, config: Settings, email: EmailSender
) -> None:
    """Mint a verification token and email it to ``user``.

    Raises whatever :meth:`EmailSender.send` raises -- callers decide how
    to handle a mail failure, since that differs between the routes that
    trigger this (silent on register, a 503 on an explicit resend).
    """
    token = await mint(session, user, EMAIL_VERIFICATION, config)
    link = f"{config.base_url.rstrip('/')}/verify?token={token}"
    await email.send(
        user.email,
        "Verify your spikeforge hub address",
        "Confirm this address to enable publishing:\n\n"
        f"{link}\n\nThis link expires in 24 hours.",
    )


async def send_password_reset_email(
    session: AsyncSession, user: User, config: Settings, email: EmailSender
) -> None:
    """Mint a reset token and email it to ``user``."""
    token = await mint(session, user, PASSWORD_RESET, config)
    link = f"{config.base_url.rstrip('/')}/reset-password?token={token}"
    await email.send(
        user.email,
        "Reset your spikeforge hub password",
        "Use this link to choose a new password:\n\n"
        f"{link}\n\nThis link expires in 1 hour.",
    )
