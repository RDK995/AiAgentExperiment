"""Focused tests for the event-driven memory pipeline listener."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.enums import AgentSex, StageOfLife
from app.db.models import EpisodicMemory, MemoryEmbedding, Relationship, SemanticBelief
from app.db.repositories import AgentCreateParams, AgentRepository
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, TerrainType, TileState, WorldState
from app.memory.embeddings import DeterministicHashEmbeddingProvider
from app.memory.pipeline import MemoryPipelineListener
from app.schemas.event import EventType, SimulationEvent


def _world() -> WorldState:
    return WorldState(
        width=3,
        height=2,
        day_index=100,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(2) for x in range(3)],
        agents=[
            AgentState(
                agent_id="agent-1",
                name="A",
                x=1,
                y=0,
                sex=AgentSex.FEMALE,
                stage_of_life=StageOfLife.ADULT,
            ),
            AgentState(
                agent_id="agent-2",
                name="B",
                x=2,
                y=0,
                sex=AgentSex.MALE,
                stage_of_life=StageOfLife.ADULT,
                hunger=98.0,
            ),
        ],
    )


@pytest.fixture
def persistence_stack():
    """Create an isolated persistence stack for the pipeline listener tests."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def session_scope():
        session: Session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    session = session_factory()
    repository = AgentRepository(session)
    actor = repository.create_agent_bundle(
        AgentCreateParams(
            name="A",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    target = repository.create_agent_bundle(
        AgentCreateParams(
            name="B",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    session.commit()
    session.close()

    try:
        yield session_scope, {"agent-1": actor.id, "agent-2": target.id}
    finally:
        engine.dispose()


def test_pipeline_writes_in_memory_memories_beliefs_and_summary_candidates() -> None:
    """A single important event should update all in-memory memory pipeline outputs."""

    world = _world()
    listener = MemoryPipelineListener(lambda: world)
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.GIFT_GIVEN,
            tick=25,
            sim_time=datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=1,
            location_y=0,
            payload={"item_type": "berries", "target_was_starving": True},
        )
    )

    actor = world.agent_by_id("agent-1")
    target = world.agent_by_id("agent-2")
    assert actor is not None and target is not None
    assert actor.memories[-1] == "Gave berries to agent-2."
    assert target.memories[-1] == "agent-1 gave me berries."
    assert "agent:agent-1:is_generous:yes" in target.beliefs
    assert "agent:agent-1:helped_me_when_hungry:yes" in target.beliefs
    assert [candidate.text for candidate in actor.daily_summary_candidates] == ["Gave berries to agent-2."]
    assert [candidate.text for candidate in target.daily_summary_candidates] == ["agent-1 gave me berries."]


def test_pipeline_persists_memories_relationships_beliefs_and_embeddings(persistence_stack) -> None:
    """When persistence is enabled, one event should fan out into all durable memory artifacts."""

    session_scope, id_map = persistence_stack
    world = _world()
    listener = MemoryPipelineListener(
        lambda: world,
        session_scope=session_scope,
        resolve_agent_id=id_map.get,
        embedding_provider=DeterministicHashEmbeddingProvider(),
    )
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.GIFT_GIVEN,
            tick=30,
            sim_time=datetime(2000, 1, 1, 13, 0, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=1,
            location_y=0,
            payload={"item_type": "berries", "target_was_starving": True},
        )
    )

    with session_scope() as session:
        memories = session.scalars(select(EpisodicMemory).order_by(EpisodicMemory.tick, EpisodicMemory.id)).all()
        beliefs = session.scalars(select(SemanticBelief).order_by(SemanticBelief.id)).all()
        relationships = session.scalars(select(Relationship).order_by(Relationship.id)).all()
        embeddings = session.scalars(select(MemoryEmbedding).order_by(MemoryEmbedding.agent_id)).all()

    assert len(memories) == 2
    assert {memory.raw_text for memory in memories} == {
        "Gave berries to agent-2.",
        "agent-1 gave me berries.",
    }
    assert len(beliefs) == 2
    assert {belief.predicate for belief in beliefs} == {"is_generous", "helped_me_when_hungry"}
    assert len(relationships) == 2
    target_view = next(
        relationship
        for relationship in relationships
        if relationship.source_agent_id == id_map["agent-2"] and relationship.target_agent_id == id_map["agent-1"]
    )
    assert target_view.trust == pytest.approx(0.18)
    assert target_view.obligation == pytest.approx(0.22)
    assert target_view.admiration == pytest.approx(0.08)
    assert len(embeddings) == 2
    assert all(len(embedding.embedding) == 1536 for embedding in embeddings)
    actor_memory = next(memory for memory in memories if memory.raw_text == "Gave berries to agent-2.")
    target_memory = next(memory for memory in memories if memory.raw_text == "agent-1 gave me berries.")
    assert actor_memory.event_type == "gift_given"
    assert actor_memory.tick == 30
    assert actor_memory.location_x == 1
    assert actor_memory.location_y == 0
    assert actor_memory.participant_ids == [id_map["agent-1"], id_map["agent-2"]]
    assert actor_memory.valence == pytest.approx(0.35)
    assert actor_memory.salience > 0.9
    assert target_memory.valence == pytest.approx(0.70)
    assert target_memory.salience > 0.9


def test_pipeline_reinforces_existing_beliefs_on_repeated_evidence(persistence_stack) -> None:
    """Repeated meaningful events should reinforce one structured belief row instead of duplicating it."""

    session_scope, id_map = persistence_stack
    world = _world()
    listener = MemoryPipelineListener(
        lambda: world,
        session_scope=session_scope,
        resolve_agent_id=id_map.get,
    )
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    for tick in (31, 32):
        bus.emit(
            SimulationEvent(
                event_id=f"evt-{tick}",
                type=EventType.INSULT_SPOKEN,
                tick=tick,
                sim_time=datetime(2000, 1, 1, 13, tick - 30, tzinfo=timezone.utc),
                actor_ids=["agent-1"],
                target_ids=["agent-2"],
                payload={"public": True},
            )
        )

    with session_scope() as session:
        beliefs = session.scalars(select(SemanticBelief)).all()

    assert len(beliefs) == 1
    assert beliefs[0].predicate == "is_hostile"
    assert beliefs[0].evidence_count == 2
    assert beliefs[0].confidence > 0.80


def test_pipeline_ignores_unsupported_low_value_events() -> None:
    """Events outside the important-event set should not write memories or beliefs."""

    world = _world()
    listener = MemoryPipelineListener(lambda: world)
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.TASK_PROGRESS,
            tick=40,
            sim_time=datetime(2000, 1, 1, 14, 0, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"task": "wander_step"},
        )
    )

    assert world.agents[0].memories == []
    assert world.agents[1].memories == []
    assert world.agents[0].beliefs == []
    assert world.agents[1].beliefs == []
    assert world.agents[0].daily_summary_candidates == []
    assert world.agents[1].daily_summary_candidates == []


def test_pipeline_persists_memories_cleanly_when_embeddings_are_disabled(persistence_stack) -> None:
    """Disabled embeddings should not prevent durable memory writes or create embedding rows."""

    session_scope, id_map = persistence_stack
    world = _world()
    listener = MemoryPipelineListener(
        lambda: world,
        session_scope=session_scope,
        resolve_agent_id=id_map.get,
    )
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.GIFT_GIVEN,
            tick=33,
            sim_time=datetime(2000, 1, 1, 13, 3, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=1,
            location_y=0,
            payload={"item_type": "berries", "target_was_starving": True},
        )
    )

    with session_scope() as session:
        memories = session.scalars(select(EpisodicMemory)).all()
        embeddings = session.scalars(select(MemoryEmbedding)).all()

    assert len(memories) == 2
    assert embeddings == []


def test_pipeline_reuses_relationship_rows_and_accumulates_supported_deltas(persistence_stack) -> None:
    """Repeated supported events should reuse directed relationship rows instead of duplicating them."""

    session_scope, id_map = persistence_stack
    world = _world()
    listener = MemoryPipelineListener(
        lambda: world,
        session_scope=session_scope,
        resolve_agent_id=id_map.get,
    )
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    for tick in (34, 35):
        bus.emit(
            SimulationEvent(
                event_id=f"evt-gift-{tick}",
                type=EventType.GIFT_GIVEN,
                tick=tick,
                sim_time=datetime(2000, 1, 1, 13, tick - 20, tzinfo=timezone.utc),
                actor_ids=["agent-1"],
                target_ids=["agent-2"],
                location_x=1,
                location_y=0,
                payload={"item_type": "berries", "target_was_starving": True},
            )
        )

    with session_scope() as session:
        relationships = session.scalars(select(Relationship).order_by(Relationship.id)).all()

    assert len(relationships) == 2
    target_view = next(
        relationship
        for relationship in relationships
        if relationship.source_agent_id == id_map["agent-2"] and relationship.target_agent_id == id_map["agent-1"]
    )
    assert target_view.trust == pytest.approx(0.36)
    assert target_view.obligation == pytest.approx(0.44)
    assert target_view.admiration == pytest.approx(0.16)


def test_pipeline_fails_fast_and_rolls_back_when_embedding_generation_errors(persistence_stack) -> None:
    """Embedding-stage failures should propagate and avoid partial persistent or in-memory writes."""

    class ExplodingEmbeddingProvider:
        def embed_text(self, text: str) -> list[float] | None:
            raise RuntimeError("embedding backend unavailable")

    session_scope, id_map = persistence_stack
    world = _world()
    listener = MemoryPipelineListener(
        lambda: world,
        session_scope=session_scope,
        resolve_agent_id=id_map.get,
        embedding_provider=ExplodingEmbeddingProvider(),
    )
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    with pytest.raises(RuntimeError, match="embedding backend unavailable"):
        bus.emit(
            SimulationEvent(
                type=EventType.GIFT_GIVEN,
                tick=36,
                sim_time=datetime(2000, 1, 1, 13, 6, tzinfo=timezone.utc),
                actor_ids=["agent-1"],
                target_ids=["agent-2"],
                location_x=1,
                location_y=0,
                payload={"item_type": "berries", "target_was_starving": True},
            )
        )

    with session_scope() as session:
        memories = session.scalars(select(EpisodicMemory)).all()
        embeddings = session.scalars(select(MemoryEmbedding)).all()

    assert memories == []
    assert embeddings == []
    assert world.agents[0].memories == []
    assert world.agents[1].memories == []


def test_pipeline_persists_public_insult_as_negative_memory_belief_and_relationship_change(persistence_stack) -> None:
    """A public insult should fan out into negative episodic memory, hostility belief, and relationship damage."""

    session_scope, id_map = persistence_stack
    world = _world()
    listener = MemoryPipelineListener(
        lambda: world,
        session_scope=session_scope,
        resolve_agent_id=id_map.get,
    )
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.INSULT_SPOKEN,
            tick=37,
            sim_time=datetime(2000, 1, 1, 13, 7, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=2,
            location_y=0,
            payload={"public": True},
        )
    )

    with session_scope() as session:
        memories = session.scalars(select(EpisodicMemory).order_by(EpisodicMemory.id)).all()
        beliefs = session.scalars(select(SemanticBelief)).all()
        relationships = session.scalars(select(Relationship)).all()

    assert {memory.raw_text for memory in memories} == {"Insulted agent-2.", "agent-1 insulted me."}
    target_memory = next(memory for memory in memories if memory.raw_text == "agent-1 insulted me.")
    assert target_memory.valence == pytest.approx(-0.80)
    assert target_memory.salience > 0.8
    assert len(beliefs) == 1
    assert beliefs[0].predicate == "is_hostile"
    target_view = next(
        relationship
        for relationship in relationships
        if relationship.source_agent_id == id_map["agent-2"] and relationship.target_agent_id == id_map["agent-1"]
    )
    assert target_view.resentment == pytest.approx(0.17)
    assert target_view.trust == pytest.approx(0.0)
    assert target_view.fear == pytest.approx(0.03)


def test_pipeline_projects_location_based_scarcity_beliefs_and_summary_candidates() -> None:
    """Scarcity events should create world beliefs and queue summary candidates for affected agents."""

    world = _world()
    listener = MemoryPipelineListener(lambda: world)
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.CROP_FAILED,
            tick=38,
            sim_time=datetime(2000, 1, 1, 13, 8, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=5,
            location_y=9,
            payload={},
        )
    )

    assert "world:resource_scarcity:food_near_5_9" in world.agents[0].beliefs
    assert "world:resource_scarcity:food_near_5_9" in world.agents[1].beliefs
    assert [candidate.text for candidate in world.agents[0].daily_summary_candidates] == ["A nearby crop failed."]
    assert [candidate.text for candidate in world.agents[1].daily_summary_candidates] == ["A nearby crop failed."]
