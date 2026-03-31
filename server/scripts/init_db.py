"""Initialize the configured database schema."""

from __future__ import annotations

from app.db.session import create_all


def main() -> None:
    """Create all ORM tables on the configured engine."""

    create_all()
    print("Database schema initialized.")


if __name__ == "__main__":
    main()
