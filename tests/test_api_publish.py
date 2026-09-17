"""Publishing over HTTP, and what the index then shows."""

from collections.abc import AsyncIterator
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.db.models import User
from tests.helpers import digest, payload

SIZE = 4096
STRONG = "quartz-lantern-9-drifting"


async def sign_in(client: AsyncClient, session: AsyncSession) -> None:
    """Register, then mark the address proven so publishing is allowed."""
    await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    user = await session.scalar(
        User.__table__.select().where(
            User.__table__.c.email == "octo@example.com"
        )
    )
    assert user is not None
    await session.execute(
        User.__table__.update()
        .where(User.__table__.c.email == "octo@example.com")
        .values(email_verified=True)
    )
    await session.commit()
    # A Core-level update does not reliably refresh an already-loaded ORM
    # object in the identity map (the row it created, from ``register``'s
    # own session.add), so the next request could still see the stale,
    # unverified copy without this.
    session.expire_all()


def intent(data: bytes, **overrides: object) -> dict[str, Any]:
    """Return an upload-intent body describing ``data``."""
    body: dict[str, Any] = {
        "name": "my-model",
        "version": "1.0.0",
        "sha256": digest(data),
        "size_bytes": len(data),
        "license": "BSD-3-Clause",
        "summary": "A reference LIF network",
    }
    body.update(overrides)
    return body


async def publish_one(
    client: AsyncClient, session: AsyncSession, data: bytes
) -> dict[str, Any]:
    """Run the whole three-call flow and return the commit body."""
    await sign_in(client, session)
    opened = await client.post("/v1/uploads", json=intent(data))
    assert opened.status_code == 200, opened.text
    slot = opened.json()
    sent = await client.put(slot["put_url"], content=data)
    assert sent.status_code == 200, sent.text
    committed = await client.post(
        f"/v1/uploads/{slot['upload_id']}/commit"
    )
    assert committed.status_code == 200, committed.text
    result: dict[str, Any] = committed.json()
    return result


async def test_the_whole_publish_flow(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = payload(SIZE)
    assert (await publish_one(client, session, data))["state"] == "published"

    listed = (await client.get("/v1/models")).json()["models"]
    assert len(listed) == 1
    assert listed[0]["id"] == "@octo/my-model"
    assert listed[0]["sha256"] == digest(data)
    # Nothing has checked this artifact beyond its checksum, and the label
    # must say exactly that rather than implying verification.
    assert listed[0]["trust"] == "unchecked"


async def test_the_index_renders_in_the_toolkit_schema(
    client: AsyncClient, session: AsyncSession
) -> None:
    await publish_one(client, session, payload(SIZE))
    document = (await client.get("/v1/index.json")).json()
    assert document["version"] == 1
    entry = document["entries"][0]
    # These are the fields spikeforge_hub.catalog validates on load.
    for field in ("id", "name", "framework", "kind", "source", "license",
                  "notes"):
        assert entry[field], f"{field} must be present and non-empty"
    assert entry["source"] == "community"
    assert entry["id"] == "@octo/my-model"
    assert "unchecked" in entry["notes"]


async def test_the_quota_reflects_a_published_artifact(
    client: AsyncClient, session: AsyncSession
) -> None:
    await publish_one(client, session, payload(SIZE))
    storage = (await client.get("/v1/me")).json()["storage"]
    assert storage["used_bytes"] == SIZE
    assert storage["reserved_bytes"] == 0


async def test_a_download_redirects_to_the_bytes(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = payload(SIZE)
    await publish_one(client, session, data)
    response = await client.get(
        "/v1/models/octo/my-model/versions/1.0.0/download"
    )
    assert response.status_code == 302
    # Content-addressed, and served by the proxy rather than this process.
    assert response.headers["location"].endswith(
        f"{digest(data)[:2]}/{digest(data)}.spkf"
    )


async def test_an_unproven_address_may_not_publish(
    client: AsyncClient,
) -> None:
    await client.post(
        "/v1/auth/register",
        json={"email": "octo@example.com", "password": STRONG},
    )
    response = await client.post("/v1/uploads", json=intent(payload(SIZE)))
    assert response.status_code == 403
    assert "verify your email" in response.json()["detail"]


async def test_a_bad_licence_is_refused_before_anything_is_reserved(
    client: AsyncClient, session: AsyncSession
) -> None:
    await sign_in(client, session)
    response = await client.post(
        "/v1/uploads", json=intent(payload(SIZE), license="see repo")
    )
    assert response.status_code == 422
    assert response.json()["title"] == "invalid license"
    # Nothing was created, so the namespace is untouched.
    assert (await client.get("/v1/models")).json()["models"] == []


@pytest.mark.parametrize("name", ["", "Bad Name", "a/b"])
async def test_a_malformed_model_name_is_refused(
    client: AsyncClient, session: AsyncSession, name: str
) -> None:
    await sign_in(client, session)
    response = await client.post(
        "/v1/uploads", json=intent(payload(SIZE), name=name)
    )
    assert response.status_code in (422,)


async def test_an_upload_without_a_content_length_is_refused(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = payload(SIZE)
    await sign_in(client, session)
    slot = (await client.post("/v1/uploads", json=intent(data))).json()

    async def chunks() -> AsyncIterator[bytes]:
        yield data

    response = await client.put(slot["put_url"], content=chunks())
    assert response.status_code == 409
    assert "Content-Length" in response.json()["detail"]


async def test_an_unpublished_model_is_not_listed(
    client: AsyncClient, session: AsyncSession
) -> None:
    data = payload(SIZE)
    await sign_in(client, session)
    slot = (await client.post("/v1/uploads", json=intent(data))).json()
    await client.put(slot["put_url"], content=data)
    # Received but not committed: it must not appear anywhere public.
    assert (await client.get("/v1/models")).json()["models"] == []
    assert (await client.get("/v1/index.json")).json()["entries"] == []
