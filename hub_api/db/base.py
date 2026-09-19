"""Declarative base and the portable column types the models share.

The service targets PostgreSQL in production and SQLite in the default test
run, so the models avoid PostgreSQL-only constructs with one exception: a JSON
column renders as ``JSONB`` on PostgreSQL through an explicit variant.
Anything else that needs dialect-specific handling belongs here, visibly,
rather than inside a model.

The declarative base, the UTC timestamp type and ``utcnow`` now come from
``capsize-commons``; ``JsonColumn`` and the ``Timestamp`` singleton stay local
because they are shaped for this schema.
"""

from typing import Any

import sqlalchemy as sa
from capsize_commons.db import Base, UtcDateTime, utcnow
from sqlalchemy.dialects.postgresql import JSONB

#: JSON payloads: ``JSONB`` on PostgreSQL, plain JSON everywhere else.
JsonColumn = sa.JSON().with_variant(JSONB, "postgresql")

#: Every timestamp column in the schema.
Timestamp: Any = UtcDateTime()

__all__ = [
    "Base",
    "JsonColumn",
    "Timestamp",
    "UtcDateTime",
    "utcnow",
]
