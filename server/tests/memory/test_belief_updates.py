"""Focused tests for event-driven semantic belief updates."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.enums import AgentSex, StageOfLife
from app.db.repositories import AgentCreateParams, AgentRepository, MemoryRepository
from app.memory.beliefs import SemanticBeliefProjector
from app.schemas.event import EventType, SimulationEvent


@pytest.fixture
def db_session() -> Session:
    """Create an isolated in-memory persistence session for belief tests."""

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


def test_selected_events_project_structured_belief_updates() -> None:
    """Gift/help and insult events should turn into predictable semantic beliefs."""

    projector = SemanticBeliefProjector()
    gift_event = SimulationEvent(
        type=EventType.GIFT_GIVEN,
        tick=30,
        sim_time=datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc),
        actor_ids=["agent-b"],
        target_ids=["agent-a"],
        payload={"target_was_starving": True},
    )
    insult_event = SimulationEvent(
        type=EventType.INSULT_SPOKEN,
        tick=31,
        sim_time=datetime(2000, 1, 1, 12, 1, tzinfo=timezone.utc),
        actor_ids=["agent-b"],
        target_ids=["agent-a"],
        payload={"public": True},
    )

    gift_beliefs = projector.beliefs_for(gift_event)
    insult_beliefs = projector.beliefs_for(insult_event)

    assert [belief.to_agent_belief_text() for belief in gift_beliefs] == [
        "agent:agent-b:is_generous:yes",
        "agent:agent-b:helped_me_when_hungry:yes",
    ]
    assert [belief.to_agent_belief_text() for belief in insult_beliefs] == [
        "agent:agent-b:is_hostile:yes"
    ]


def test_repeated_belief_evidence_increases_confidence_and_evidence_count(db_session: Session) -> None:
    """Repeated support for the same belief should update the existing row in place."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=0,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    subject_id = uuid.uuid4()

    first = memory_repository.support_belief(
        agent_id=agent.id,
        subject_type="agent",
        subject_id=subject_id,
        predicate="is_generous",
        object_value="yes",
        confidence=0.70,
        last_supported_tick=40,
    )
    second = memory_repository.support_belief(
        agent_id=agent.id,
        subject_type="agent",
        subject_id=subject_id,
        predicate="is_generous",
        object_value="yes",
        confidence=0.72,
        last_supported_tick=41,
    )

    assert first.id == second.id
    assert second.evidence_count == 2
    assert second.confidence > 0.72

    persisted = db_session.scalars(select(type(second))).all()
    assert len(persisted) == 1


def test_scarcity_events_project_location_based_beliefs_for_all_affected_agents() -> None:
    """Scarcity-style events should become structured world beliefs keyed by location."""

    projector = SemanticBeliefProjector()
    scarcity_event = SimulationEvent(
        type=EventType.FOOD_STORE_EMPTY,
        tick=50,
        sim_time=datetime(2000, 1, 1, 12, 5, tzinfo=timezone.utc),
        actor_ids=["agent-a"],
        target_ids=["agent-b"],
        location_x=4,
        location_y=7,
        payload={},
    )

    beliefs = projector.beliefs_for(scarcity_event)

    assert [belief.agent_id for belief in beliefs] == ["agent-a", "agent-b"]
    assert all(belief.subject_type == "world" for belief in beliefs)
    assert all(belief.predicate == "resource_scarcity" for belief in beliefs)
    assert all(belief.object_value == "food_near_4_7" for belief in beliefs)
