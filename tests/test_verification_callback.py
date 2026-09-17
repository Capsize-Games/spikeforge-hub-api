"""The sandbox's callback: signing, state transitions, and what it reveals.

Covers the whole path in three layers, matching the other test files' split
between an HTTP layer and the functions underneath it: signature
verification (:mod:`hub_api.auth.signatures`), the state machine
(:mod:`hub_api.uploads.verify`), the ``repository_dispatch`` trigger
(:mod:`hub_api.uploads.dispatch`), and the endpoint that wires them
together (:mod:`hub_api.routes.verifications`).
"""

import json
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from hub_api.app import build
from hub_api.auth.signatures import matches, sign
from hub_api.config import Settings
from hub_api.config import settings as settings_dep
from hub_api.db.engine import db_session
from hub_api.db.models.model_version import (
    PUBLISHED,
    REJECTED,
    UPLOADED,
    VERIFYING,
    ModelVersion,
)
from hub_api.db.models.user import User
from hub_api.errors import ConflictError, NotFoundError
from hub_api.storage.factory import storage as storage_dep
from hub_api.storage.volume import VolumeStorage
from hub_api.uploads import dispatch
from hub_api.uploads.verify import InvalidReportError, apply_report
from tests.helpers import digest, payload

SIZE = 4096
STRONG = "quartz-lantern-9-drifting"
SECRET = "sandbox-shared-secret"


def verifying(config: Settings, **overrides: object) -> Settings:
    """Return ``config`` with verification required and a secret set."""
    fields: dict[str, object] = {
        **config.model_dump(),
        "require_verification": True,
        "verification_secret": SECRET,
    }
    fields.update(overrides)
    return Settings(**fields)


@asynccontextmanager
async def client_for(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> AsyncIterator[AsyncClient]:
    """Return a client wired to ``config`` instead of the shared fixture's.

    These tests need ``require_verification`` and ``verification_secret``
    on, which the default ``config`` fixture leaves off so the rest of the
    suite is not forced through the verification path.
    """
    app = build()
    app.dependency_overrides[db_session] = lambda: session
    app.dependency_overrides[settings_dep] = lambda: config
    app.dependency_overrides[storage_dep] = lambda: storage
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://hub.test"
    ) as opened:
        yield opened


async def sign_in(client: AsyncClient, session: AsyncSession) -> None:
    """Register, then mark the address proven so publishing is allowed."""
    await client.post(
        "/v1/auth/register",
        json={"email": "sandbox@example.com", "password": STRONG},
    )
    await session.execute(
        User.__table__.update()
        .where(User.__table__.c.email == "sandbox@example.com")
        .values(email_verified=True)
    )
    await session.commit()


def intent(data: bytes) -> dict[str, Any]:
    """Return an upload-intent body describing ``data``."""
    return {
        "name": "my-model",
        "version": "1.0.0",
        "sha256": digest(data),
        "size_bytes": len(data),
        "license": "BSD-3-Clause",
    }


async def enter_verifying(
    client: AsyncClient, session: AsyncSession, data: bytes
) -> str:
    """Run reserve/receive/commit and return the id of a VERIFYING version."""
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
    assert committed.json()["state"] == VERIFYING
    return str(slot["upload_id"])


async def post_report(
    client: AsyncClient,
    version_id: str,
    report: dict[str, Any],
    secret: str = SECRET,
) -> httpx.Response:
    """POST ``report`` to the callback, correctly signed by default."""
    body = json.dumps(report).encode()
    return await client.post(
        f"/internal/v1/verifications/{version_id}",
        content=body,
        headers={
            "content-type": "application/json",
            "X-Verification-Signature": sign(secret, body),
        },
    )


# --- the endpoint, over HTTP ------------------------------------------------


async def test_a_passing_report_publishes_the_version(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    data = payload(SIZE)
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        version_id = await enter_verifying(client, session, data)
        report = {
            "passed": True,
            "reasons": [],
            "nir": {"nodes": 12},
            "compat": {"verdict": "exact"},
            "energy": {"sop": 4096},
        }
        response = await post_report(client, version_id, report)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["state"] == PUBLISHED
        assert body["published_at"] is not None

        shown = await client.get("/v1/models/sandbox/my-model")
        assert shown.status_code == 200
        assert shown.json()["trust"] == "machine-checked"
        # Stored verbatim: every field the sandbox sent comes back, not
        # only the one field (``passed``) this service itself reads.
        assert shown.json()["verification"] == report


async def test_a_failing_report_rejects_and_names_why(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    data = payload(SIZE)
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        version_id = await enter_verifying(client, session, data)
        report = {
            "passed": False,
            "reasons": ["weights are not loadable with weights_only=True"],
        }
        response = await post_report(client, version_id, report)
        assert response.status_code == 200, response.text
        assert response.json()["state"] == REJECTED

        # No version of this model ever published, yet the handle/slug
        # route must still answer with why -- never a bare 404 hiding it.
        shown = await client.get("/v1/models/sandbox/my-model")
        assert shown.status_code == 200
        assert shown.json()["state"] == REJECTED
        assert shown.json()["rejection_reasons"] == report["reasons"]


async def test_a_failing_report_without_reasons_is_refused(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    data = payload(SIZE)
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        version_id = await enter_verifying(client, session, data)
        response = await post_report(
            client, version_id, {"passed": False, "reasons": []}
        )
        assert response.status_code == 422
        assert response.json()["title"] == "invalid verification report"

        # Refused before anything changed: the version is still waiting.
        version = await session.get(ModelVersion, uuid.UUID(version_id))
        assert version is not None
        assert version.state == VERIFYING


async def test_a_missing_signature_is_refused(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        version_id = await enter_verifying(client, session, payload(SIZE))
        response = await client.post(
            f"/internal/v1/verifications/{version_id}",
            content=b'{"passed": true, "reasons": []}',
        )
        assert response.status_code == 401


async def test_a_wrong_signature_is_refused(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        version_id = await enter_verifying(client, session, payload(SIZE))
        response = await post_report(
            client, version_id, {"passed": True, "reasons": []},
            secret="not-the-right-secret",
        )
        assert response.status_code == 401


async def test_an_unconfigured_secret_refuses_service_unavailable(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    # require_verification alone can hold a version in VERIFYING; the
    # deployment simply has nobody who could ever call back correctly.
    unset = verifying(config, verification_secret="")
    async with client_for(session, storage, unset) as client:
        version_id = await enter_verifying(client, session, payload(SIZE))
        response = await post_report(
            client, version_id, {"passed": True, "reasons": []}
        )
        assert response.status_code == 503


async def test_an_unknown_version_is_refused(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        response = await post_report(
            client, str(uuid.uuid4()), {"passed": True, "reasons": []}
        )
        assert response.status_code == 404


async def test_a_version_not_awaiting_verification_is_refused(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        await sign_in(client, session)
        data = payload(SIZE)
        opened = await client.post("/v1/uploads", json=intent(data))
        slot = opened.json()
        await client.put(slot["put_url"], content=data)
        # Received, but never committed: still UPLOADED, not VERIFYING.
        response = await post_report(
            client, slot["upload_id"], {"passed": True, "reasons": []}
        )
        assert response.status_code == 409
        assert "uploaded" in response.json()["detail"]


async def test_a_report_cannot_be_replayed_after_publication(
    session: AsyncSession, storage: VolumeStorage, config: Settings
) -> None:
    strict = verifying(config)
    async with client_for(session, storage, strict) as client:
        version_id = await enter_verifying(client, session, payload(SIZE))
        report = {"passed": True, "reasons": []}
        first = await post_report(client, version_id, report)
        assert first.status_code == 200
        second = await post_report(client, version_id, report)
        assert second.status_code == 409


async def test_the_commit_triggers_the_sandbox_dispatch(
    session: AsyncSession,
    storage: VolumeStorage,
    config: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def _client(**kwargs: object) -> "_RecordingAsyncClient":
        return _RecordingAsyncClient(calls, **kwargs)

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", _client)
    strict = verifying(
        config,
        verification_dispatch_repo="capsize-games/spikeforge",
        verification_dispatch_token="ghp_example",
    )
    async with client_for(session, storage, strict) as client:
        version_id = await enter_verifying(client, session, payload(SIZE))
    assert len(calls) == 1
    call = calls[0]
    assert call["url"].endswith(
        "/repos/capsize-games/spikeforge/dispatches"
    )
    assert call["json"]["event_type"] == "verify_model_version"
    payload_sent = call["json"]["client_payload"]
    assert payload_sent["version_id"] == version_id
    assert payload_sent["callback_url"].endswith(
        f"/internal/v1/verifications/{version_id}"
    )
    assert call["headers"]["Authorization"] == "Bearer ghp_example"


# --- hub_api.uploads.verify, directly ---------------------------------------


async def _verifying_version(session: AsyncSession) -> ModelVersion:
    """Return a bare ModelVersion row already in VERIFYING, unsaved model."""
    from hub_api.db.models.hub_model import HubModel
    from hub_api.db.models.user import User as UserModel

    owner = UserModel(
        id=uuid.uuid4(),
        handle="direct",
        email="direct@example.com",
        email_verified=True,
        can_publish=True,
        storage_limit=1_000_000,
    )
    model = HubModel(
        id=uuid.uuid4(),
        owner_id=owner.id,
        slug="direct-model",
        license="BSD-3-Clause",
    )
    version = ModelVersion(
        id=uuid.uuid4(),
        model_id=model.id,
        version="1.0.0",
        sha256=digest(b"x"),
        size_bytes=1,
        object_key="ab/" + digest(b"x") + ".spkf",
        state=VERIFYING,
    )
    # Flushed one at a time, in dependency order: PostgreSQL enforces the
    # foreign keys these rows carry, unlike SQLite's default, and a single
    # add_all() here is not guaranteed to insert owner before model before
    # version.
    session.add(owner)
    await session.flush()
    session.add(model)
    await session.flush()
    session.add(version)
    await session.flush()
    return version


async def test_apply_report_publishes_on_a_pass(
    session: AsyncSession,
) -> None:
    version = await _verifying_version(session)
    report = {"passed": True, "reasons": []}
    updated = await apply_report(session, version.id, report)
    assert updated.state == PUBLISHED
    assert updated.published_at is not None
    assert updated.verification == report


async def test_apply_report_rejects_on_a_named_failure(
    session: AsyncSession,
) -> None:
    version = await _verifying_version(session)
    report = {"passed": False, "reasons": ["compat verdict: incompatible"]}
    updated = await apply_report(session, version.id, report)
    assert updated.state == REJECTED
    assert updated.published_at is None
    assert updated.verification == report


async def test_apply_report_refuses_a_bare_failure(
    session: AsyncSession,
) -> None:
    version = await _verifying_version(session)
    with pytest.raises(InvalidReportError):
        await apply_report(session, version.id, {"passed": False})


async def test_apply_report_refuses_a_version_not_verifying(
    session: AsyncSession,
) -> None:
    version = await _verifying_version(session)
    version.state = UPLOADED
    await session.flush()
    with pytest.raises(ConflictError, match="uploaded"):
        await apply_report(
            session, version.id, {"passed": True, "reasons": []}
        )


async def test_apply_report_refuses_an_unknown_version(
    session: AsyncSession,
) -> None:
    with pytest.raises(NotFoundError):
        await apply_report(
            session, uuid.uuid4(), {"passed": True, "reasons": []}
        )


# --- hub_api.auth.signatures -------------------------------------------------


def test_matches_accepts_a_correct_signature() -> None:
    body = b'{"passed": true}'
    assert matches(SECRET, body, sign(SECRET, body))


def test_matches_refuses_a_tampered_body() -> None:
    signature = sign(SECRET, b'{"passed": true}')
    assert not matches(SECRET, b'{"passed": false}', signature)


def test_matches_refuses_the_wrong_secret() -> None:
    body = b'{"passed": true}'
    assert not matches("a-different-secret", body, sign(SECRET, body))


# --- hub_api.uploads.dispatch, directly --------------------------------------


class _FakeResponse:
    """A response that never complains, standing in for httpx's."""

    def raise_for_status(self) -> None:
        """Do nothing: every fake delivery in these tests "succeeds"."""


class _RecordingAsyncClient:
    """A stand-in for httpx.AsyncClient that records one POST call."""

    def __init__(
        self, calls: list[dict[str, Any]], **_: object
    ) -> None:
        self._calls = calls

    async def __aenter__(self) -> "_RecordingAsyncClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def post(
        self, url: str, json: dict[str, Any], headers: dict[str, str]
    ) -> _FakeResponse:
        self._calls.append({"url": url, "json": json, "headers": headers})
        return _FakeResponse()


async def test_notify_is_a_noop_without_a_configured_sandbox(
    config: Settings,
) -> None:
    version = ModelVersion(
        id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        version="1.0.0",
        sha256=digest(b"x"),
        size_bytes=1,
        object_key="k",
    )
    # config carries no dispatch repo/token: this must not touch the
    # network at all, real httpx included.
    await dispatch.notify(config, version)


async def test_notify_swallows_a_delivery_failure(
    config: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _refuse(**_: object) -> "_RecordingAsyncClient":
        raise httpx.ConnectError("no route to host")

    monkeypatch.setattr(dispatch.httpx, "AsyncClient", _refuse)
    configured = Settings(
        **{
            **config.model_dump(),
            "verification_dispatch_repo": "o/r",
            "verification_dispatch_token": "t",
        }
    )
    version = ModelVersion(
        id=uuid.uuid4(),
        model_id=uuid.uuid4(),
        version="1.0.0",
        sha256=digest(b"x"),
        size_bytes=1,
        object_key="k",
    )
    # Must not raise: the VERIFYING row already committed is the source of
    # truth, and a lost webhook is recoverable by hand.
    await dispatch.notify(configured, version)
