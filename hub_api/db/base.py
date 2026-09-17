"""Declarative base and the portable column types the models share.

The service targets PostgreSQL in production and SQLite in the default test
run, so the models avoid PostgreSQL-only constructs with one exception: a JSON
column renders as ``JSONB`` on PostgreSQL through an explicit variant.
Anything else that needs dialect-specific handling belongs here, visibly,
rather than inside a model.
"""

from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import DeclarativeBase

#: JSON payloads: ``JSONB`` on PostgreSQL, plain JSON everywhere else.
JsonColumn = sa.JSON().with_variant(JSONB, "postgresql")


def utcnow() -> datetime:
    """Return the current time as a timezone-aware UTC datetime."""
    return datetime.now(UTC)


class UtcDateTime(sa.types.TypeDecorator[datetime]):
    """A timestamp that is always timezone-aware UTC in Python.

    PostgreSQL's ``timestamptz`` round-trips an aware datetime; SQLite has no
    timezone type and hands back a naive one. Code that then compares it to
    an aware ``utcnow()`` raises ``TypeError`` -- on SQLite only, which means
    the default test run fails and a PostgreSQL deployment silently does not,
    or the reverse for whichever comparison happens to be written first.

    Rather than remembering to normalise at every comparison, both directions
    are handled once here: a naive value is refused on the way in, and every
    value read back is tagged UTC.
    """

    impl = sa.DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Refuse a naive datetime and normalise the rest to UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError(
                "refusing to store a naive datetime: attach a timezone, or "
                "use hub_api.db.base.utcnow()"
            )
        return value.astimezone(UTC)

    def process_result_value(
        self, value: datetime | None, dialect: Dialect
    ) -> datetime | None:
        """Tag a value read from a dialect without timezones as UTC."""
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


#: Every timestamp column in the schema.
Timestamp: Any = UtcDateTime()


class Base(DeclarativeBase):
    """Declarative base for every hub table."""
