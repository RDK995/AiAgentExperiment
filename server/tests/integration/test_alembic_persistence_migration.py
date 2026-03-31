"""Smoke test for the persistence Alembic migration."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text


def test_alembic_upgrade_head_creates_persistence_tables(tmp_path: Path) -> None:
    """Running the Alembic baseline should create the expected persistence tables."""

    database_path = tmp_path / "alembic_persistence.db"
    alembic_config = Config(str(Path("server/alembic.ini").resolve()))
    alembic_config.set_main_option("script_location", str(Path("server/migrations").resolve()))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(alembic_config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())

        assert "agents" in table_names
        assert "agent_traits" in table_names
        assert "agent_needs" in table_names
        assert "agent_skills" in table_names
        assert "relationships" in table_names
        assert "pair_bonds" in table_names
        assert "pregnancies" in table_names
        assert "agent_goals" in table_names
        assert "episodic_memories" in table_names
        assert "semantic_beliefs" in table_names
        assert "memory_embeddings" in table_names
        assert "world_events" in table_names
        assert "inventories" in table_names

        relationship_indexes = {index["name"] for index in inspector.get_indexes("relationships")}
        goal_indexes = {index["name"] for index in inspector.get_indexes("agent_goals")}
        world_event_indexes = {index["name"] for index in inspector.get_indexes("world_events")}
        memory_indexes = {index["name"] for index in inspector.get_indexes("episodic_memories")}
        relationship_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("relationships")}
        memory_embedding_foreign_keys = inspector.get_foreign_keys("memory_embeddings")
        agent_goal_foreign_keys = inspector.get_foreign_keys("agent_goals")
        goal_columns = {column["name"]: column for column in inspector.get_columns("agent_goals")}
        world_event_columns = {column["name"]: column for column in inspector.get_columns("world_events")}
        inventory_columns = {column["name"]: column for column in inspector.get_columns("inventories")}

        assert "ix_relationships_source_agent_id" in relationship_indexes
        assert "ix_relationships_target_agent_id" in relationship_indexes
        assert "ix_agent_goals_agent_id_status" in goal_indexes
        assert "ix_world_events_tick" in world_event_indexes
        assert "ix_episodic_memories_agent_id_tick" in memory_indexes
        assert "uq_relationships_source_target" in relationship_uniques
        assert any(foreign_key["referred_table"] == "episodic_memories" for foreign_key in memory_embedding_foreign_keys)
        assert any(foreign_key["referred_table"] == "agents" for foreign_key in memory_embedding_foreign_keys)
        assert any(foreign_key["referred_table"] == "agents" for foreign_key in agent_goal_foreign_keys)
        assert goal_columns["success_condition"]["nullable"] is False
        assert world_event_columns["payload"]["nullable"] is False
        assert inventory_columns["metadata"]["nullable"] is False

        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "20260331_2200"
    finally:
        engine.dispose()
