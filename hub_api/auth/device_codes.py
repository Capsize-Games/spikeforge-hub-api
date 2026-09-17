"""The device-authorization flow (RFC 8628): the ``device_code`` grant.

The fallback for the case where a loopback hand-off in
:mod:`hub_api.auth.grants` cannot work -- a remote session, a machine with no
browser handler, a locked-down desktop. The app shows ``user_code``; a
signed-in person types it in at ``/activate``; the app polls
``/oauth/token`` until it is approved.
"""

import secrets
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.auth import credentials
from hub_api.auth.grant_support import (
    active_owner,
    expiry,
    parse_scope,
    scopes_of,
)
from hub_api.config import Settings
from hub_api.db.base import utcnow
from hub_api.db.models.device_code import APPROVED, DENIED, PENDING, DeviceCode
from hub_api.db.models.user import User
from hub_api.errors import (
    AuthorizationPendingError,
    InvalidRequestError,
    NotFoundError,
    SlowDownError,
    UnauthorizedError,
)
from hub_api.schemas.oauth import OAuthTokenBody
from hub_api.tokens import hash_token, new_token

#: Unambiguous characters for a code a person reads off a screen and types.
_USER_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
#: How much slower a client must poll after polling too fast (RFC 8628).
_SLOW_DOWN_STEP = 5


@dataclass(frozen=True)
class DeviceCodeIssued:
    """A freshly created device-flow attempt."""

    device_code: str
    user_code: str
    interval_seconds: int


def _new_user_code() -> str:
    """Return a short code, grouped for reading, with no ambiguous glyphs."""
    chars = [secrets.choice(_USER_CODE_ALPHABET) for _ in range(8)]
    return f"{''.join(chars[:4])}-{''.join(chars[4:])}"


async def start(
    session: AsyncSession, client_id: str, scope: str, config: Settings
) -> DeviceCodeIssued:
    """Create a pending device-flow attempt and return what the app needs."""
    token = new_token(prefix="sfh_dc_")
    user_code = _new_user_code()
    row = DeviceCode(
        device_code_hash=token.hashed,
        user_code=user_code,
        client_id=client_id,
        scopes=parse_scope(scope),
        expires_at=expiry(config.device_code_ttl_seconds),
    )
    session.add(row)
    await session.flush()
    return DeviceCodeIssued(
        device_code=token.plaintext,
        user_code=user_code,
        interval_seconds=row.interval_seconds,
    )


async def approve(session: AsyncSession, user: User, user_code: str) -> None:
    """Approve the pending device-code attempt named ``user_code``."""
    row = await session.scalar(
        sa.select(DeviceCode).where(DeviceCode.user_code == user_code)
    )
    if row is None or row.state != PENDING or row.expires_at <= utcnow():
        raise NotFoundError(
            "no pending device code for that user_code; it may have "
            "expired or already been used"
        )
    row.user_id = user.id
    row.state = APPROVED
    await session.flush()


async def _find(session: AsyncSession, device_code: str) -> DeviceCode:
    """Return the ``DeviceCode`` row for ``device_code``, or refuse it."""
    row = await session.scalar(
        sa.select(DeviceCode).where(
            DeviceCode.device_code_hash == hash_token(device_code)
        )
    )
    if row is None:
        raise UnauthorizedError("no such device code")
    return row


def _check_not_finished(row: DeviceCode) -> None:
    """Refuse a device code whose outcome is already settled.

    Checked before the interval is tracked: once expired, redeemed, or
    denied, a poll is refused every time regardless of how fast it arrives,
    the same way ``credentials.rotate`` refuses an already-exchanged refresh
    token unconditionally rather than folding it into rate-limiting.
    """
    if row.expires_at <= utcnow():
        raise UnauthorizedError("this device code has expired")
    if row.redeemed_at is not None:
        raise UnauthorizedError("this device code was already redeemed")
    if row.state == DENIED:
        raise UnauthorizedError("sign-in was denied for this device code")


async def _track_poll(session: AsyncSession, row: DeviceCode) -> None:
    """Record this poll and enforce RFC 8628 ``slow_down``.

    Committed immediately: a rejection here has to survive the request's
    rollback, or the interval it just raised could never be observed by the
    next poll.
    """
    now = utcnow()
    too_fast = (
        row.last_polled_at is not None
        and (now - row.last_polled_at).total_seconds() < row.interval_seconds
    )
    row.last_polled_at = now
    if too_fast:
        row.interval_seconds += _SLOW_DOWN_STEP
    await session.commit()
    if too_fast:
        raise SlowDownError(
            "polling too fast; wait interval_seconds between polls",
            interval_seconds=row.interval_seconds,
        )


def _check_approved(row: DeviceCode) -> None:
    """Refuse a device code a person has not yet approved."""
    if row.state == PENDING:
        raise AuthorizationPendingError(
            "the user has not yet approved this device code"
        )


async def exchange(
    session: AsyncSession, body: OAuthTokenBody, config: Settings
) -> credentials.IssuedPair:
    """Poll a device-code grant, enforcing the interval and its state."""
    if not body.device_code:
        raise InvalidRequestError(
            "the device_code grant requires device_code"
        )
    row = await _find(session, body.device_code)
    _check_not_finished(row)
    await _track_poll(session, row)
    _check_approved(row)
    row.redeemed_at = utcnow()
    user = await active_owner(session, row.user_id)
    return await credentials.issue_pair(
        session, user, scopes_of(row.scopes), config
    )
