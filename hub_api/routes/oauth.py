"""The hub's first-party OAuth endpoints for the desktop sign-in flow.

Loopback PKCE (``/oauth/authorize`` and the ``authorization_code`` grant on
``/oauth/token``) and its device-flow fallback (``/oauth/device_code``,
``/activate``, and the ``device_code`` grant). Distinct from
``hub_api.routes.auth``'s ``/oauth/{provider}/start`` and
``/oauth/{provider}/callback``, which broker an external provider's own
consent screen rather than issuing this service's tokens directly.

This service has no HTML sign-in page, so ``/oauth/authorize`` and
``/activate`` both require a caller who already holds a hub session (the
existing ``/v1/auth/*`` cookie flow) rather than offering to sign one in --
a deliberate narrowing of the plan's "sign in in-browser" aspiration.
"""

from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from hub_api.auth import credentials, device_codes, grants
from hub_api.deps import ConfigDep, CurrentUser, SessionDep
from hub_api.schemas.oauth import DeviceCodeStartBody, OAuthTokenBody

router = APIRouter()


@router.get("/oauth/authorize")
async def authorize(
    user: CurrentUser,
    session: SessionDep,
    config: ConfigDep,
    client_id: str,
    redirect_uri: str,
    code_challenge: str,
    state: str,
    response_type: str = "code",
    code_challenge_method: str = "S256",
    scope: str = "",
) -> RedirectResponse:
    """Issue an authorization code and send the browser back to the app."""
    code = await grants.authorize(
        session,
        user,
        client_id=client_id,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method=code_challenge_method,
        response_type=response_type,
        scope=scope,
        config=config,
    )
    await session.commit()
    return RedirectResponse(
        _with_query(redirect_uri, code=code, state=state), status_code=302
    )


def _with_query(url: str, **params: str) -> str:
    """Return ``url`` with ``params`` appended to its query string.

    A merge rather than a bare append: a client's ``redirect_uri`` is free
    to carry its own query already (RFC 8252 allows it), and clobbering that
    with a literal ``?`` would break the redirect.
    """
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    query.extend(params.items())
    return urlunsplit(parts._replace(query=urlencode(query)))


@router.post("/oauth/token")
async def token(
    body: OAuthTokenBody, session: SessionDep, config: ConfigDep
) -> dict[str, Any]:
    """Redeem an authorization code or an approved device code for tokens."""
    if body.grant_type == "authorization_code":
        pair = await grants.exchange_authorization_code(
            session, body, config
        )
    else:
        pair = await device_codes.exchange(session, body, config)
    await session.commit()
    return _pair_response(pair)


def _pair_response(pair: credentials.IssuedPair) -> dict[str, Any]:
    """Return a token pair shaped like ``/v1/auth/refresh``'s response."""
    return {
        "access_token": pair.access_token,
        "refresh_token": pair.refresh_token,
        "token_type": "Bearer",
        "expires_in": pair.expires_in,
        "scope": " ".join(pair.scopes),
    }


@router.post("/oauth/device_code", status_code=201)
async def device_code(
    body: DeviceCodeStartBody, session: SessionDep, config: ConfigDep
) -> dict[str, Any]:
    """Start a device-flow attempt and return the code to poll and show."""
    issued = await device_codes.start(
        session, body.client_id, body.scope, config
    )
    await session.commit()
    return {
        "device_code": issued.device_code,
        "user_code": issued.user_code,
        "interval_seconds": issued.interval_seconds,
        "expires_in": config.device_code_ttl_seconds,
        "verification_uri": f"{config.base_url.rstrip('/')}/activate",
    }


@router.get("/activate")
async def activate(
    user: CurrentUser, session: SessionDep, user_code: str
) -> dict[str, str]:
    """Approve a pending device-code attempt for the signed-in account."""
    await device_codes.approve(session, user, user_code)
    await session.commit()
    return {"status": "approved"}
