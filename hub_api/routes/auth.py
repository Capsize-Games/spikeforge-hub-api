"""Sign-up, sign-in, sign-out, the provider redirects, and account recovery."""

import logging
from typing import Any

from capsize_auth import hash_password
from capsize_auth.oauth2 import OAuth2Error, OAuthProfile, generate
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from hub_api.auth import accounts, credentials, sessions, verification
from hub_api.auth.providers import providers
from hub_api.config import Settings
from hub_api.db.models.user import User
from hub_api.db.models.verification_token import (
    EMAIL_VERIFICATION,
    PASSWORD_RESET,
)
from hub_api.deps import ConfigDep, CurrentUser, EmailDep, SessionDep
from hub_api.email.base import EmailSender, EmailSendError
from hub_api.errors import ServiceUnavailableError, UnauthorizedError
from hub_api.oauth_state import read_state, write_state
from hub_api.routes.cookies import (
    clear_session,
    cookie_name,
    set_session,
)
from hub_api.schemas.auth import (
    LoginBody,
    PasswordResetConfirmBody,
    PasswordResetRequestBody,
    RefreshBody,
    RegisterBody,
    VerifyBody,
)

router = APIRouter()
logger = logging.getLogger(__name__)

#: Returned for every outcome of a reset request -- an unknown address, a
#: mail failure, or a success -- so none of them can be told apart from the
#: response, the same protection ``accounts.sign_in`` gives sign-in.
_RESET_RESPONSE = {
    "status": "if that address has an account, a reset email is on its way"
}


@router.get("/v1/auth/providers")
async def enabled_providers() -> dict[str, Any]:
    """List the providers this deployment has enabled.

    Only configured ones: a sign-in page should render buttons that work.
    """
    return {
        "password": True,
        "oauth": [
            {"id": info.id, "display_name": info.display_name}
            for info in providers().available()
        ],
    }


@router.post("/v1/auth/register", status_code=201)
async def register(
    body: RegisterBody,
    response: Response,
    request: Request,
    session: SessionDep,
    config: ConfigDep,
    email: EmailDep,
) -> dict[str, Any]:
    """Create an account, sign it in, and start email verification."""
    user = await accounts.register(
        session, str(body.email), body.password, config
    )
    cookie = await sessions.start(
        session, user, config, request.headers.get("user-agent", "")
    )
    await _send_verification(session, user, config, email)
    await session.commit()
    set_session(response, cookie, config)
    return {"handle": user.handle, "email_verified": user.email_verified}


async def _send_verification(
    session: SessionDep, user: User, config: Settings, email: EmailSender
) -> None:
    """Send the verification email, logging rather than failing on error.

    An unconfigured or unreachable mail transport must not make account
    creation itself start failing -- that would be a worse regression than
    the missing verification flow this closes.
    """
    try:
        await verification.send_verification_email(
            session, user, config, email
        )
    except EmailSendError:
        logger.exception(
            "could not send verification email to %s", user.handle
        )


@router.post("/v1/auth/login")
async def login(
    body: LoginBody,
    response: Response,
    request: Request,
    session: SessionDep,
    config: ConfigDep,
) -> dict[str, Any]:
    """Sign in with an address and a password."""
    user = await accounts.sign_in(
        session, str(body.email), body.password
    )
    cookie = await sessions.start(
        session, user, config, request.headers.get("user-agent", "")
    )
    await session.commit()
    set_session(response, cookie, config)
    return {"handle": user.handle, "email_verified": user.email_verified}


@router.post("/v1/auth/logout")
async def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    config: ConfigDep,
) -> dict[str, str]:
    """End the current browser session."""
    cookie = request.cookies.get(cookie_name(config))
    if cookie:
        await sessions.revoke(session, cookie)
        await session.commit()
    clear_session(response, config)
    return {"status": "signed out"}


@router.post("/v1/auth/refresh")
async def refresh(
    body: RefreshBody, session: SessionDep, config: ConfigDep
) -> dict[str, Any]:
    """Exchange a refresh token for a new pair."""
    pair = await credentials.rotate(
        session, body.refresh_token, config
    )
    await session.commit()
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "token_type": "Bearer",
        "expires_in": pair.expires_in,
        "scope": " ".join(pair.scopes),
    }


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str, config: ConfigDep) -> RedirectResponse:
    """Send the browser to a provider's consent screen."""
    client = providers().client(provider)
    pkce = generate()
    state = write_state(provider, pkce.verifier, config)
    target = client.authorize_url(state, code_challenge=pkce.challenge)
    return RedirectResponse(target, status_code=302)


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    code: str,
    state: str,
    request: Request,
    response: Response,
    session: SessionDep,
    config: ConfigDep,
) -> dict[str, Any]:
    """Complete a provider sign-in and open a session."""
    profile = await _profile_from(provider, code, state, config)
    user = await accounts.link_or_create(session, profile, config)
    cookie = await sessions.start(
        session, user, config, request.headers.get("user-agent", "")
    )
    await session.commit()
    set_session(response, cookie, config)
    return {"handle": user.handle, "provider": provider}


async def _profile_from(
    provider: str, code: str, state: str, config: ConfigDep
) -> OAuthProfile:
    """Exchange a callback for the provider's profile, or refuse."""
    verifier = read_state(state, provider, config)
    try:
        return await providers().client(provider).complete(code, verifier)
    except OAuth2Error as error:
        raise UnauthorizedError(
            f"{provider} sign-in failed: {error}"
        ) from error


@router.post("/v1/auth/sessions/revoke-all")
async def revoke_all(
    user: CurrentUser, session: SessionDep
) -> dict[str, int]:
    """Sign the account out everywhere."""
    revoked = await sessions.revoke_all(session, user.id)
    await session.commit()
    return {"revoked": revoked}


@router.post("/v1/auth/verify")
async def verify_email(
    body: VerifyBody, session: SessionDep
) -> dict[str, bool]:
    """Redeem a verification token and mark the address proven."""
    user = await verification.redeem(session, body.token, EMAIL_VERIFICATION)
    user.email_verified = True
    await session.commit()
    return {"email_verified": True}


@router.post("/v1/auth/verify/resend")
async def resend_verification(
    user: CurrentUser, session: SessionDep, config: ConfigDep, email: EmailDep
) -> dict[str, str]:
    """Send a fresh verification email to the signed-in account.

    Authenticated, so sending it unconditionally raises no account-existence
    concern -- unlike the anonymous password-reset request below.
    """
    if user.email_verified:
        return {"status": "already verified"}
    try:
        await verification.send_verification_email(
            session, user, config, email
        )
    except EmailSendError as error:
        raise ServiceUnavailableError(
            "could not send the verification email; try again shortly"
        ) from error
    await session.commit()
    return {"status": "verification email sent"}


@router.post("/v1/auth/password/reset")
async def request_password_reset(
    body: PasswordResetRequestBody,
    session: SessionDep,
    config: ConfigDep,
    email: EmailDep,
) -> dict[str, str]:
    """Start a password reset, without revealing whether the address exists.

    Every outcome -- unknown address, a mail failure, success -- returns
    the identical body: the same protection ``accounts.sign_in`` already
    gives the login form against becoming an account-existence oracle.
    """
    await _try_send_reset(session, str(body.email), config, email)
    await session.commit()
    return _RESET_RESPONSE


async def _try_send_reset(
    session: SessionDep, address: str, config: Settings, email: EmailSender
) -> None:
    """Mint and send a reset email, swallowing every failure.

    A found-vs-not-found difference here, or an infra failure surfacing any
    differently than a success, would both reopen the oracle this endpoint
    exists to close -- so nothing raises out of this helper.
    """
    try:
        found = await accounts.by_email(session, address)
        if found is not None:
            await verification.send_password_reset_email(
                session, found, config, email
            )
    except Exception:
        logger.exception("password reset request failed for %s", address)


@router.post("/v1/auth/password/reset/confirm")
async def confirm_password_reset(
    body: PasswordResetConfirmBody, session: SessionDep
) -> dict[str, str]:
    """Redeem a reset token, set a new password, and end other sessions.

    Checked before the token is redeemed: a password the policy rejects
    must not burn the caller's one reset link before they get a chance to
    retry with a stronger one.
    """
    accounts.check_password_strength(body.password)
    user = await verification.redeem(session, body.token, PASSWORD_RESET)
    user.password_hash = hash_password(body.password)
    user.token_version += 1
    await sessions.revoke_all(session, user.id)
    await session.commit()
    return {"status": "password reset"}
