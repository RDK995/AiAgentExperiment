"""SQLAlchemy column helpers with PostgreSQL-aware fallbacks."""

from __future__ import annotations

from collections.abc import Sequence
import uuid

from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects import postgresql
from sqlalchemy.types import TypeDecorator

try:
    from pgvector.sqlalchemy import Vector as PgVector
except ImportError:  # pragma: no cover - optional dependency
    PgVector = None


JSONB = JSON().with_variant(postgresql.JSONB(), "postgresql")


class UUIDArrayType(TypeDecorator[list[uuid.UUID]]):
    """Store UUID arrays as PostgreSQL arrays or JSON on non-PostgreSQL backends."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(postgresql.ARRAY(Uuid(as_uuid=True)))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Sequence[uuid.UUID | str] | None, dialect):
        if value is None:
            return []
        if dialect.name == "postgresql":
            return [item if isinstance(item, uuid.UUID) else uuid.UUID(str(item)) for item in value]
        return [str(item) for item in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        return [item if isinstance(item, uuid.UUID) else uuid.UUID(str(item)) for item in value]


class Vector1536(TypeDecorator[list[float]]):
    """Store 1536-d embeddings via pgvector when available, else JSON."""

    impl = JSON
    cache_ok = True
    dimension = 1536

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql" and PgVector is not None:
            return dialect.type_descriptor(PgVector(self.dimension))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        return [float(component) for component in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return [float(component) for component in value]


def pgvector_enabled() -> bool:
    """Return whether pgvector support is available in the Python environment."""

    return PgVector is not None
