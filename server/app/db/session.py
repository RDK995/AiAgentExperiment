"""Database engine and session helpers."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings
from app.db.base import Base, import_models


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Create the shared SQLAlchemy engine from application settings."""

    settings = get_settings()
    return create_engine(
        settings.database_url,
        echo=settings.database_echo,
        future=True,
        pool_pre_ping=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the shared configured sessionmaker."""

    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def create_all() -> None:
    """Create all known tables on the configured engine."""

    import_models()
    Base.metadata.create_all(get_engine())


@contextmanager
def session_scope() -> Iterator[Session]:
    """Provide a transactional scope around ORM operations."""

    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
