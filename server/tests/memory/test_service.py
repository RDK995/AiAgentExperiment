"""Focused tests for the persistence-aware memory query service."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.enums import AgentSex, StageOfLife
from app.db.repositories import (
    AgentCreateParams,
    AgentRepository,
    EpisodicMemoryCreateParams,
    MemoryRepository,
    SemanticBeliefCreateParams,
)
from app.memory.service import MemoryQueryService


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite-backed ORM session for memory service tests."""

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


def test_query_service_filters_episodic_memories_by_salience_and_recency(db_session: Session) -> None:
    """The query service should expose sorted, filtered episodic memory records."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    service = MemoryQueryService(memory_repository)
    agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Dane",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=agent.id,
            tick=10,
            event_type="greeting",
            raw_text="Said hello at the well.",
            valence=0.1,
            salience=0.15,
        )
    )
    memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=agent.id,
            tick=20,
            event_type="gift_given",
            raw_text="Received berries while starving.",
            valence=0.7,
            salience=0.91,
        )
    )
    memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=agent.id,
            tick=30,
            event_type="crop_failed",
            raw_text="The west field failed.",
            valence=-0.8,
            salience=0.82,
        )
    )

    salience_sorted = service.query_episodic_memories(agent.id, min_salience=0.80, sort_by="salience", limit=5)
    recency_sorted = service.query_episodic_memories(agent.id, min_tick=15, sort_by="recency", limit=5)

    assert [record.raw_text for record in salience_sorted] == [
        "Received berries while starving.",
        "The west field failed.",
    ]
    assert [record.tick for record in recency_sorted] == [30, 20]


def test_query_service_filters_semantic_beliefs_by_subject_predicate_and_confidence(db_session: Session) -> None:
    """The query service should expose structured semantic belief filtering."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    service = MemoryQueryService(memory_repository)
    agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Eli",
            sex=AgentSex.INTERSEX,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    subject_id = uuid.uuid4()
    memory_repository.create_belief(
        SemanticBeliefCreateParams(
            agent_id=agent.id,
            subject_type="agent",
            subject_id=subject_id,
            predicate="is_generous",
            object_value="yes",
            confidence=0.85,
            last_supported_tick=10,
        )
    )
    memory_repository.create_belief(
        SemanticBeliefCreateParams(
            agent_id=agent.id,
            subject_type="world",
            predicate="resource_scarcity",
            object_value="food_near_2_1",
            confidence=0.72,
            last_supported_tick=11,
        )
    )

    beliefs = service.query_semantic_beliefs(
        agent.id,
        subject_type="agent",
        predicate="is_generous",
        min_confidence=0.80,
    )

    assert len(beliefs) == 1
    assert beliefs[0].subject_type == "agent"
    assert beliefs[0].predicate == "is_generous"
    assert beliefs[0].confidence == pytest.approx(0.85)
