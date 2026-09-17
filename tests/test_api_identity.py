"""The identity endpoints, over HTTP."""

from httpx import AsyncClient

STRONG = "quartz-lantern-9-drifting"


async def test_health_reports_ok(client: AsyncClient) -> None:
    response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


async def test_providers_lists_password_and_no_oauth(
    client: AsyncClient,
) -> None:
    body = (await client.get("/v1/auth/providers")).json()
    assert body["password"] is True
    # None are configured in the test settings, so none are offered.
    assert body["oauth"] == []


async def test_register_then_read_the_account(client: AsyncClient) -> None:
    created = await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    assert created.status_code == 201
    assert created.json()["handle"] == "octo"

    me = await client.get("/v1/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "octo@example.com"
    assert body["storage"]["used_bytes"] == 0
    assert body["storage"]["limit_bytes"] == 4 * 1024**2
    # Registration does not prove the address, so publishing waits.
    assert body["can_publish"] is False


async def test_a_weak_password_is_refused_as_a_problem_document(
    client: AsyncClient,
) -> None:
    response = await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": "password1"},
    )
    assert response.status_code == 422
    assert response.headers["content-type"].startswith(
        "application/problem+json"
    )
    assert response.json()["title"] == "weak password"


async def test_an_anonymous_caller_is_refused(client: AsyncClient) -> None:
    response = await client.get("/v1/me")
    assert response.status_code == 401
    assert response.json()["status"] == 401


async def test_logout_ends_the_session(client: AsyncClient) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    assert (await client.get("/v1/me")).status_code == 200
    assert (await client.post("/v1/auth/logout")).status_code == 200
    assert (await client.get("/v1/me")).status_code == 401


async def test_login_with_the_wrong_password_is_refused(
    client: AsyncClient,
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    await client.post("/v1/auth/logout")
    response = await client.post(
        "/v1/auth/login",
        json={"email": "octo@example.com", "password": "wrong-password-x"},
    )
    assert response.status_code == 401


async def test_a_personal_access_token_authenticates(
    client: AsyncClient,
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    minted = await client.post(
        "/v1/tokens", json={"name": "ci", "scopes": ["models:read"]}
    )
    assert minted.status_code == 201
    token = minted.json()["token"]
    assert token.startswith("sfh_pat_")

    await client.post("/v1/auth/logout")
    response = await client.get(
        "/v1/me", headers={"authorization": f"Bearer {token}"}
    )
    assert response.status_code == 200


async def test_a_revoked_token_stops_working(client: AsyncClient) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    minted = (await client.post("/v1/tokens", json={"name": "ci"})).json()
    listed = (await client.get("/v1/tokens")).json()["tokens"]
    assert len(listed) == 1
    # The value itself is never returned again.
    assert "token" not in listed[0]

    await client.delete(f"/v1/tokens/{listed[0]['id']}")
    await client.post("/v1/auth/logout")
    response = await client.get(
        "/v1/me", headers={"authorization": f"Bearer {minted['token']}"}
    )
    assert response.status_code == 401


async def test_an_unknown_scope_is_refused(client: AsyncClient) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    response = await client.post(
        "/v1/tokens", json={"name": "ci", "scopes": ["models:destroy"]}
    )
    assert response.status_code == 422
