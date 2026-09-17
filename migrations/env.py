"""Alembic environment.

The URL comes from the service's own settings rather than alembic.ini, so
there is one place credentials are configured. The async driver is swapped
for its sync counterpart here: migrations run once at deploy time and gain
nothing from an event loop, while a sync run is far simpler to reason about
when one fails halfway.
"""

from alembic import context
from sqlalchemy import engine_from_config, pool

from hub_api.config import settings
from hub_api.db import models
from hub_api.db.base import Base, UtcDateTime

config = context.config

# Importing the models package is what registers every table on the
# metadata. Naming its export here states that dependency outright, rather
# than leaving an import that looks unused and inviting a linter
# suppression on top of it.
_REGISTERED_TABLES = tuple(models.__all__)

target_metadata = Base.metadata

_SYNC_DRIVERS = {
    "postgresql+psycopg": "postgresql+psycopg",
    "sqlite+aiosqlite": "sqlite",
}


def _sync_url() -> str:
    """Return the configured URL with a synchronous driver."""
    url = settings().database_url
    for async_prefix, sync_prefix in _SYNC_DRIVERS.items():
        if url.startswith(async_prefix):
            return url.replace(async_prefix, sync_prefix, 1)
    return url


def _render_item(type_: str, obj: object, autogen_context: object) -> object:
    """Render a custom column type as the DDL it actually produces.

    ``UtcDateTime`` is a type decorator: everything it does happens in Python,
    on the way to and from the driver. The column it creates is an ordinary
    timestamp-with-timezone, so that is what a migration should say -- and it
    keeps revisions from importing application code, which is what makes an
    old revision still runnable after the application has moved on.
    """
    if type_ == "type" and isinstance(obj, UtcDateTime):
        return "sa.DateTime(timezone=True)"
    return False


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of running it."""
    context.configure(
        url=_sync_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_item=_render_item,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Apply migrations against the configured database."""
    section = config.get_section(config.config_ini_section) or {}
    section["sqlalchemy.url"] = _sync_url()
    connectable = engine_from_config(
        section, prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_item=_render_item,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
