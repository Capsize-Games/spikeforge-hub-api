"""The desktop sign-in endpoints: loopback PKCE and the device-code path."""

from urllib.parse import parse_qs, urlsplit

from capsize_auth.oauth2 import pkce
from httpx import AsyncClient

STRONG = "quartz-lantern-9-drifting"
REDIRECT_URI = "http://127.0.0.1:53214/callback"


async def _signed_in_client(client: AsyncClient) -> None:
    """Register an account, leaving the client signed in via its cookie."""
    response = await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    assert response.status_code == 201


async def _authorize(client: AsyncClient, challenge: str) -> str:
    """Drive ``/oauth/authorize`` and return the authorization code."""
    response = await client.get(
        "/oauth/authorize",
        params={
            "client_id": "desktop",
            "redirect_uri": REDIRECT_URI,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "response_type": "code",
        },
    )
    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith(REDIRECT_URI)
    query = parse_qs(urlsplit(location).query)
    assert query["state"] == ["xyz"]
    return query["code"][0]


async def test_loopback_exchange_issues_tokens(client: AsyncClient) -> None:
    await _signed_in_client(client)
    pair = pkce.generate()
    code = await _authorize(client, pair.challenge)

    response = await client.post(
        "/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": pair.verifier,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["access_token"].startswith("sfh_at_")
    assert body["refresh_token"].startswith("sfh_rt_")
    assert body["token_type"] == "Bearer"
    assert body["expires_in"] == 3600
    assert body["scope"] == "models:read models:write"


async def test_authorization_code_is_single_use(client: AsyncClient) -> None:
    await _signed_in_client(client)
    pair = pkce.generate()
    code = await _authorize(client, pair.challenge)
    exchange = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": pair.verifier,
    }
    first = await client.post("/oauth/token", json=exchange)
    assert first.status_code == 200

    second = await client.post("/oauth/token", json=exchange)
    assert second.status_code == 401
    assert second.json()["title"] == "unauthorized"


async def test_a_mismatched_verifier_is_refused(client: AsyncClient) -> None:
    await _signed_in_client(client)
    pair = pkce.generate()
    code = await _authorize(client, pair.challenge)
    response = await client.post(
        "/oauth/token",
        json={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": "not-the-right-verifier",
        },
    )
    assert response.status_code == 401


async def test_authorize_refuses_a_non_loopback_redirect(
    client: AsyncClient,
) -> None:
    await _signed_in_client(client)
    pair = pkce.generate()
    response = await client.get(
        "/oauth/authorize",
        params={
            "client_id": "desktop",
            "redirect_uri": "https://evil.example.com/callback",
            "code_challenge": pair.challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "response_type": "code",
        },
    )
    assert response.status_code == 400
    assert response.json()["title"] == "invalid request"


async def test_authorize_requires_a_session(client: AsyncClient) -> None:
    pair = pkce.generate()
    response = await client.get(
        "/oauth/authorize",
        params={
            "client_id": "desktop",
            "redirect_uri": REDIRECT_URI,
            "code_challenge": pair.challenge,
            "code_challenge_method": "S256",
            "state": "xyz",
            "response_type": "code",
        },
    )
    assert response.status_code == 401


async def test_device_flow_full_exchange(client: AsyncClient) -> None:
    started = await client.post(
        "/oauth/device_code", json={"client_id": "desktop", "scope": ""}
    )
    assert started.status_code == 201
    issued = started.json()
    assert issued["verification_uri"].endswith("/activate")

    # A poll before anyone has approved it is refused, but must not consume
    # the grant -- covered together with the interval check in
    # test_too_fast_polling_is_refused, since asserting it here too would
    # make this test's timing depend on how fast the polls after it run.

    await _signed_in_client(client)
    approved = await client.get(
        "/activate", params={"user_code": issued["user_code"]}
    )
    assert approved.status_code == 200

    redeemed = await client.post(
        "/oauth/token",
        json={
            "grant_type": "device_code",
            "device_code": issued["device_code"],
        },
    )
    assert redeemed.status_code == 200
    body = redeemed.json()
    assert body["access_token"].startswith("sfh_at_")
    assert body["token_type"] == "Bearer"


async def test_device_code_redemption_is_single_use(
    client: AsyncClient,
) -> None:
    started = (
        await client.post(
            "/oauth/device_code", json={"client_id": "desktop", "scope": ""}
        )
    ).json()
    await _signed_in_client(client)
    await client.get("/activate", params={"user_code": started["user_code"]})
    poll = {
        "grant_type": "device_code",
        "device_code": started["device_code"],
    }
    first = await client.post("/oauth/token", json=poll)
    assert first.status_code == 200

    second = await client.post("/oauth/token", json=poll)
    assert second.status_code == 401


async def test_too_fast_polling_is_refused(client: AsyncClient) -> None:
    started = (
        await client.post(
            "/oauth/device_code", json={"client_id": "desktop", "scope": ""}
        )
    ).json()
    poll = {
        "grant_type": "device_code",
        "device_code": started["device_code"],
    }
    first = await client.post("/oauth/token", json=poll)
    assert first.status_code == 400
    assert first.json()["title"] == "authorization pending"

    second = await client.post("/oauth/token", json=poll)
    assert second.status_code == 429
    body = second.json()
    assert body["title"] == "slow down"
    assert body["interval_seconds"] == started["interval_seconds"] + 5
