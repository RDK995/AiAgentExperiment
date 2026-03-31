"""Compact regression tests for the persistence layer's riskiest guarantees."""

from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, func, inspect, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.enums import (
    AgentSex,
    GoalSource,
    GoalStatus,
    GoalType,
    InventoryOwnerType,
    KinshipType,
    StageOfLife,
)
from app.db.models import (
    Agent,
    AgentGoal,
    AgentNeed,
    AgentSkill,
    AgentTrait,
    EpisodicMemory,
    Inventory,
    MemoryEmbedding,
    Relationship,
    WorldEvent,
)
from app.db.types import JSONB, UUIDArrayType, Vector1536, pgvector_enabled


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite-backed ORM session for persistence regressions."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_relationship_uniqueness_regression_guard(db_session: Session) -> None:
    """The directed relationship uniqueness guarantee should not regress."""

    source = _persist_agent_graph(db_session, _make_agent(name="Source"))
    target = _persist_agent_graph(db_session, _make_agent(name="Target"))

    db_session.add(
        Relationship(
            source_agent_id=source.id,
            target_agent_id=target.id,
            familiarity=0.3,
            trust=0.4,
            attraction=0.0,
            resentment=0.0,
            admiration=0.1,
            fear=0.0,
            obligation=0.0,
            dependency=0.0,
            kinship_type=KinshipType.NONE,
        )
    )
    db_session.commit()

    db_session.add(
        Relationship(
            source_agent_id=source.id,
            target_agent_id=target.id,
            familiarity=0.8,
            trust=0.9,
            attraction=0.0,
            resentment=0.0,
            admiration=0.0,
            fear=0.0,
            obligation=0.0,
            dependency=0.0,
            kinship_type=KinshipType.NONE,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_cascade_delete_regression_guard_for_agent_owned_rows(db_session: Session) -> None:
    """Deleting an agent should still cascade through key owned persistence records."""

    agent = _persist_agent_graph(db_session, _make_agent(name="Cascade"))
    memory = EpisodicMemory(
        agent_id=agent.id,
        tick=10,
        event_type="storm",
        raw_text="Sheltered during a storm.",
        valence=-0.2,
        salience=0.6,
        participant_ids=[agent.id],
    )
    goal = AgentGoal(
        agent_id=agent.id,
        goal_type=GoalType.SAFETY,
        title="Rebuild shelter",
        priority=1.2,
        horizon_days=2,
        status=GoalStatus.ACTIVE,
        source=GoalSource.REFLECTION,
        created_tick=10,
        updated_tick=10,
    )
    inventory = Inventory(
        owner_type=InventoryOwnerType.AGENT,
        owner_id=agent.id,
        item_type="wood",
        quantity=3,
        metadata_json={"dry": True},
    )
    db_session.add_all([memory, goal, inventory])
    db_session.commit()

    db_session.add(
        MemoryEmbedding(
            memory_id=memory.id,
            agent_id=agent.id,
            embedding=[0.1, 0.2, 0.3],
        )
    )
    db_session.commit()

    db_session.delete(agent)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Agent)) == 0
    assert db_session.scalar(select(func.count()).select_from(AgentGoal)) == 0
    assert db_session.scalar(select(func.count()).select_from(EpisodicMemory)) == 0
    assert db_session.scalar(select(func.count()).select_from(MemoryEmbedding)) == 0


def test_json_and_uuid_array_round_trip_regression_guard(db_session: Session) -> None:
    """Structured JSON and UUID-array fields should keep round-tripping cleanly."""

    agent = _persist_agent_graph(db_session, _make_agent(name="RoundTrip"))
    participant_ids = [agent.id, uuid.uuid4()]
    actor_ids = [agent.id]
    target_ids = [uuid.uuid4()]

    goal = AgentGoal(
        agent_id=agent.id,
        goal_type=GoalType.EXPLORATION,
        title="Map the northern ridge",
        priority=1.0,
        horizon_days=6,
        status=GoalStatus.ACTIVE,
        source=GoalSource.SEEDED,
        success_condition={"visited_tiles": 12},
        created_tick=4,
        updated_tick=4,
    )
    memory = EpisodicMemory(
        agent_id=agent.id,
        tick=4,
        event_type="expedition",
        raw_text="Explored the ridge with neighbors.",
        valence=0.7,
        salience=0.9,
        participant_ids=participant_ids,
    )
    world_event = WorldEvent(
        tick=4,
        event_type="ridge_expedition",
        actor_ids=actor_ids,
        target_ids=target_ids,
        payload={"weather": "clear", "distance": 5},
    )
    inventory = Inventory(
        owner_type=InventoryOwnerType.AGENT,
        owner_id=agent.id,
        item_type="berries",
        quantity=5,
        metadata_json={"fresh": True},
    )
    db_session.add_all([goal, memory, world_event, inventory])
    db_session.commit()
    db_session.expire_all()

    persisted_goal = db_session.get(AgentGoal, goal.id)
    persisted_memory = db_session.get(EpisodicMemory, memory.id)
    persisted_event = db_session.get(WorldEvent, world_event.id)
    persisted_inventory = db_session.get(Inventory, inventory.id)

    assert persisted_goal is not None
    assert persisted_goal.success_condition == {"visited_tiles": 12}
    assert persisted_memory is not None
    assert persisted_memory.participant_ids == participant_ids
    assert persisted_event is not None
    assert persisted_event.actor_ids == actor_ids
    assert persisted_event.target_ids == target_ids
    assert persisted_event.payload == {"weather": "clear", "distance": 5}
    assert persisted_inventory is not None
    assert persisted_inventory.metadata_json == {"fresh": True}


def test_migration_smoke_regression_guard(tmp_path: Path) -> None:
    """The baseline Alembic migration should continue to create core schema structures."""

    database_path = tmp_path / "persistence_regression.db"
    alembic_config = Config(str(Path("server/alembic.ini").resolve()))
    alembic_config.set_main_option("script_location", str(Path("server/migrations").resolve()))
    alembic_config.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(alembic_config, "head")

    engine = create_engine(f"sqlite+pysqlite:///{database_path}", future=True)
    try:
        inspector = inspect(engine)
        table_names = set(inspector.get_table_names())
        relationship_uniques = {constraint["name"] for constraint in inspector.get_unique_constraints("relationships")}

        assert "agents" in table_names
        assert "relationships" in table_names
        assert "agent_goals" in table_names
        assert "episodic_memories" in table_names
        assert "memory_embeddings" in table_names
        assert "world_events" in table_names
        assert "uq_relationships_source_target" in relationship_uniques

        with engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        assert revision == "20260331_2200"
    finally:
        engine.dispose()


def test_pgvector_wiring_regression_guard() -> None:
    """PostgreSQL-oriented type helpers should keep compiling to the expected shapes."""

    jsonb_type = str(JSONB.dialect_impl(postgresql.dialect())).lower()
    array_type = str(UUIDArrayType().load_dialect_impl(postgresql.dialect())).lower()
    vector_type = str(Vector1536().load_dialect_impl(postgresql.dialect())).lower()

    assert "jsonb" in jsonb_type
    assert "array" in array_type
    assert "uuid" in array_type
    if pgvector_enabled():
        assert "vector" in vector_type
    else:
        assert "json" in vector_type


def _persist_agent_graph(db_session: Session, agent: Agent) -> Agent:
    """Persist an agent with required one-to-one rows for regression tests."""

    agent.traits = AgentTrait(
        sociability=0.5,
        aggression=0.2,
        conscientiousness=0.6,
        curiosity=0.7,
        family_orientation=0.4,
        risk_tolerance=0.3,
        libido=0.5,
        emotional_stability=0.8,
        memory_fidelity=0.75,
        learning_rate=0.65,
    )
    agent.needs = AgentNeed(
        hunger=5.0,
        thirst=8.0,
        fatigue=12.0,
        warmth=70.0,
        health=95.0,
        stress=10.0,
        loneliness=15.0,
        safety=90.0,
    )
    agent.skills = AgentSkill()
    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)
    return agent


def _make_agent(name: str, sex: AgentSex = AgentSex.FEMALE) -> Agent:
    """Build a valid agent for persistence regression tests."""

    return Agent(
        name=name,
        sex=sex,
        birth_tick=0,
        current_tile_x=2,
        current_tile_y=3,
        stage_of_life=StageOfLife.ADULT,
    )
