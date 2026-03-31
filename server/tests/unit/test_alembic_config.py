"""Unit tests for Alembic database URL resolution."""

from app.db.alembic_config import DEFAULT_ALEMBIC_DATABASE_URL, resolve_alembic_database_url


def test_resolve_alembic_database_url_prefers_runtime_settings_over_default_ini_url() -> None:
    """Runtime DATABASE_URL should override the checked-in Alembic placeholder URL."""

    resolved = resolve_alembic_database_url(
        DEFAULT_ALEMBIC_DATABASE_URL,
        "postgresql+psycopg://village:secret@db/autonomous_village",
    )

    assert resolved == "postgresql+psycopg://village:secret@db/autonomous_village"


def test_resolve_alembic_database_url_preserves_explicitly_injected_url() -> None:
    """Tests and CLI callers should keep an explicitly provided Alembic URL."""

    resolved = resolve_alembic_database_url(
        "sqlite+pysqlite:////tmp/alembic-smoke.db",
        "postgresql+psycopg://village:secret@db/autonomous_village",
    )

    assert resolved == "sqlite+pysqlite:////tmp/alembic-smoke.db"
