"""Fixtures: an isolated database, a temporary volume, and an account.

The default run uses SQLite, which needs no service and no container. The
schema avoids PostgreSQL-only constructs apart from an explicit JSONB
variant, and the ``postgres`` marker runs the same suite against a real
instance -- see the README. What SQLite cannot check is dialect-specific
behaviour, which is exactly why that second run exists rather than being
assumed unnecessary.
"""

import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hub_api.config import Settings
from hub_api.db.base import Base
from hub_api.db.models import User
from hub_api.storage.volume import VolumeStorage

if TYPE_CHECKING:
    from httpx import AsyncClient

_MIB = 1024**2


@pytest.fixture
def config(tmp_path: Path) -> Settings:
    """Return settings pointed at a temporary volume, with small limits."""
    return Settings(
        artifact_root=tmp_path / "artifacts",
        tmp_root=tmp_path / "tmp",
        database_url="sqlite+aiosqlite:///:memory:",
        token_secret="t" * 32,
        default_storage_limit=4 * _MIB,
        max_artifact_bytes=2 * _MIB,
        footprint_cap_bytes=16 * _MIB,
        volume_free_floor_bytes=0,
        max_models_per_user=3,
        max_versions_per_model=2,
        max_uploads_per_day=5,
        publishing_gate="open",
        require_verification=False,
        # The test client speaks plain HTTP, and a Secure cookie is
        # correctly refused over that, so the unprefixed name is used here
        # exactly as it would be for local development.
        cookie_secure=False,
    )


@pytest.fixture
def storage(config: Settings) -> VolumeStorage:
    """Return storage backed by the temporary volume."""
    return VolumeStorage(config.artifact_root, config.tmp_root)


#: Set to a PostgreSQL URL to run the suite against a real instance instead
#: of SQLite. See the README; the ``postgres`` marker covers the same tests.
POSTGRES_URL_ENV = "HUB_TEST_DATABASE_URL"


def _database_url() -> str:
    """Return the URL the suite should run against."""
    return os.environ.get(POSTGRES_URL_ENV) or "sqlite+aiosqlite:///:memory:"


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Yield a session against a fresh schema.

    The schema is dropped and recreated per test rather than rolled back, so
    a PostgreSQL run cannot leak state between tests through a sequence or a
    constraint the transaction did not cover.
    """
    engine = create_async_engine(_database_url())
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as opened:
        yield opened
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def user(session: AsyncSession, config: Settings) -> User:
    """Return a saved, verified account allowed to publish."""
    return await make_user(session, config)


async def make_user(
    session: AsyncSession,
    config: Settings,
    handle: str = "tester",
    **overrides: object,
) -> User:
    """Create and save an account."""
    fields: dict[str, object] = {
        "handle": handle,
        "email": f"{handle}@example.com",
        "email_verified": True,
        "can_publish": True,
        "storage_limit": config.default_storage_limit,
    }
    fields.update(overrides)
    created = User(id=uuid.uuid4(), **fields)
    session.add(created)
    await session.flush()
    return created


@pytest.fixture
async def client(
    session: AsyncSession, config: Settings, storage: VolumeStorage
) -> AsyncIterator["AsyncClient"]:
    """Yield an HTTP client wired to the test database and volume.

    The dependencies are overridden rather than the environment configured,
    so a test never touches the real volume path or a real database.
    """
    from httpx import ASGITransport, AsyncClient

    from hub_api.app import build
    from hub_api.config import settings as settings_dep
    from hub_api.db.engine import db_session
    from hub_api.storage.factory import storage as storage_dep

    app = build()
    app.dependency_overrides[db_session] = lambda: session
    app.dependency_overrides[settings_dep] = lambda: config
    app.dependency_overrides[storage_dep] = lambda: storage
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://hub.test"
    ) as opened:
        yield opened
