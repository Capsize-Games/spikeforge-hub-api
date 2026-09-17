"""Sign-up, sign-in, sign-out, and the provider redirects."""

from typing import Any

from capsize_auth.oauth2 import OAuth2Error, OAuthProfile, generate
from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from hub_api.auth import accounts, credentials, sessions
from hub_api.auth.providers import providers
from hub_api.deps import ConfigDep, CurrentUser, SessionDep
from hub_api.errors import UnauthorizedError
from hub_api.oauth_state import read_state, write_state
from hub_api.routes.cookies import (
    clear_session,
    cookie_name,
    set_session,
)
from hub_api.schemas.auth import LoginBody, RefreshBody, RegisterBody

router = APIRouter()


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
) -> dict[str, Any]:
    """Create an account and sign it in."""
    user = await accounts.register(
        session, str(body.email), body.password, config
    )
    cookie = await sessions.start(
        session, user, config, request.headers.get("user-agent", "")
    )
    await session.commit()
    set_session(response, cookie, config)
    return {"handle": user.handle, "email_verified": user.email_verified}


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
