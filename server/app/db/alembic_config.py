"""Helpers for resolving Alembic database configuration safely."""

from __future__ import annotations


DEFAULT_ALEMBIC_DATABASE_URL = "sqlite+pysqlite:///./autonomous_village.db"


def resolve_alembic_database_url(configured_url: str | None, settings_url: str) -> str:
    """Choose the Alembic target database URL.

    Use the runtime settings URL when Alembic is still pointing at its default
    placeholder database. Preserve explicitly injected URLs used by tests or
    CLI callers.
    """

    if not configured_url or configured_url == DEFAULT_ALEMBIC_DATABASE_URL:
        return settings_url
    return configured_url
