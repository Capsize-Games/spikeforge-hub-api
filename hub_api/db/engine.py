"""Async engine, session factory, and the request-scoped session dependency."""

from collections.abc import AsyncIterator
from functools import lru_cache

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from hub_api.config import settings


@lru_cache(maxsize=1)
def engine() -> AsyncEngine:
    """Return the process-wide async engine."""
    return create_async_engine(
        settings().database_url,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def session_factory() -> async_sessionmaker[AsyncSession]:
    """Return the process-wide session factory."""
    return async_sessionmaker(engine(), expire_on_commit=False)


async def db_session() -> AsyncIterator[AsyncSession]:
    """Yield a request-scoped session, rolling back on an exception."""
    async with session_factory()() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
