"""Loopback PKCE (RFC 8252): the hub's own ``authorization_code`` grant.

Distinct from ``hub_api.routes.auth``'s ``/oauth/{provider}/start`` and
``/oauth/{provider}/callback``, which broker an *external* provider's consent
screen and hand back a profile. This issues the hub's own access and refresh
tokens directly, to a caller who already holds a hub session -- the desktop
app's primary sign-in path, per ``plans/hub_accounts_plan.md`` §3.3. The
device-code fallback lives alongside this in
:mod:`hub_api.auth.device_codes`.
"""

from urllib.parse import urlsplit

import sqlalchemy as sa
from capsize_auth.oauth2 import pkce
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
from hub_api.db.models.auth_code import AuthCode
from hub_api.db.models.user import User
from hub_api.errors import InvalidRequestError, UnauthorizedError
from hub_api.schemas.oauth import OAuthTokenBody
from hub_api.tokens import hash_token, new_token

#: The only loopback hosts a native app may redirect to (RFC 8252 §7.3).
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _check_loopback_redirect(redirect_uri: str) -> None:
    """Refuse a ``redirect_uri`` that is not a loopback address."""
    parsed = urlsplit(redirect_uri)
    if parsed.scheme != "http" or parsed.hostname not in _LOOPBACK_HOSTS:
        raise InvalidRequestError(
            "redirect_uri must be an http loopback address (127.0.0.1, "
            "::1, or localhost), per RFC 8252"
        )


def _check_pkce_method(method: str) -> None:
    """Refuse any PKCE transform but S256, the only one trusted here."""
    if method != pkce.METHOD:
        raise InvalidRequestError(
            f"code_challenge_method must be {pkce.METHOD!r}"
        )


def _check_response_type(response_type: str) -> None:
    """Refuse anything but the one response type this endpoint issues."""
    if response_type != "code":
        raise InvalidRequestError("response_type must be 'code'")


async def authorize(
    session: AsyncSession,
    user: User,
    *,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    code_challenge_method: str,
    response_type: str,
    scope: str,
    config: Settings,
) -> str:
    """Issue a single-use authorization code for a signed-in account."""
    _check_response_type(response_type)
    _check_loopback_redirect(redirect_uri)
    _check_pkce_method(code_challenge_method)
    token = new_token(prefix="sfh_ac_")
    session.add(
        AuthCode(
            code_hash=token.hashed,
            user_id=user.id,
            client_id=client_id,
            redirect_uri=redirect_uri,
            code_challenge=code_challenge,
            scopes=parse_scope(scope),
            expires_at=expiry(config.authorization_code_ttl_seconds),
        )
    )
    await session.flush()
    return token.plaintext


async def _find_auth_code(session: AsyncSession, code: str) -> AuthCode:
    """Return the ``AuthCode`` row for ``code``, or refuse it."""
    row = await session.scalar(
        sa.select(AuthCode).where(AuthCode.code_hash == hash_token(code))
    )
    if row is None:
        raise UnauthorizedError("no such authorization code")
    return row


def _check_auth_code(
    row: AuthCode, redirect_uri: str, verifier: str
) -> None:
    """Refuse a code that is spent, expired, mismatched, or PKCE-invalid.

    A second presentation of an already-used code is treated the same way
    ``credentials.rotate`` treats a replayed refresh token: as evidence the
    code leaked, not as a retry to honour.
    """
    if row.used_at is not None:
        raise UnauthorizedError(
            "this authorization code was already redeemed"
        )
    if row.expires_at <= utcnow():
        raise UnauthorizedError("this authorization code has expired")
    if row.redirect_uri != redirect_uri:
        raise UnauthorizedError(
            "redirect_uri does not match the request that issued this code"
        )
    if not pkce.verify(verifier, row.code_challenge):
        raise UnauthorizedError("the PKCE verifier does not match")


async def exchange_authorization_code(
    session: AsyncSession, body: OAuthTokenBody, config: Settings
) -> credentials.IssuedPair:
    """Verify PKCE, redeem the code once, and mint a token pair."""
    if not body.code or not body.redirect_uri or not body.code_verifier:
        raise InvalidRequestError(
            "the authorization_code grant requires code, redirect_uri, "
            "and code_verifier"
        )
    row = await _find_auth_code(session, body.code)
    _check_auth_code(row, body.redirect_uri, body.code_verifier)
    row.used_at = utcnow()
    user = await active_owner(session, row.user_id)
    return await credentials.issue_pair(
        session, user, scopes_of(row.scopes), config
    )
