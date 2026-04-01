"""Repository-level tests for the persistence layer."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, event, select
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
from app.db.models import AgentGoal, EpisodicMemory, Inventory, Relationship, SemanticBelief, WorldEvent
from app.db.repositories import (
    AgentCreateParams,
    AgentRepository,
    EpisodicMemoryCreateParams,
    GoalCreateParams,
    GoalUpdateParams,
    MemoryRepository,
    RelationshipCreateParams,
    SemanticBeliefCreateParams,
    WorldEventCreateParams,
    WorldRepository,
)
from app.schemas.event import WorldEventSchema


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite-backed ORM session for repository tests."""

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


def test_agent_repository_creates_and_fetches_full_agent_bundle(db_session: Session) -> None:
    """The agent repository should create and reload a complete agent graph."""

    repository = AgentRepository(db_session)
    created = repository.create_agent_bundle(
        AgentCreateParams(
            name="Nia",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=4,
            current_tile_y=7,
            stage_of_life=StageOfLife.ADULT,
            trait_values={"curiosity": 0.9},
            need_values={"hunger": 12.0},
            skill_values={"gathering": 3.5},
        )
    )
    goal = repository.add_goal(
        AgentGoal(
            agent_id=created.id,
            goal_type=GoalType.EXPLORATION,
            title="Scout the western forest",
            priority=1.2,
            horizon_days=5,
            status=GoalStatus.ACTIVE,
            source=GoalSource.SEEDED,
            created_tick=1,
            updated_tick=1,
        )
    )
    db_session.commit()

    fetched = repository.get_agent_with_related(created.id)

    assert fetched is not None
    assert fetched.name == "Nia"
    assert fetched.traits.curiosity == pytest.approx(0.9)
    assert fetched.needs.hunger == pytest.approx(12.0)
    assert fetched.skills.gathering == pytest.approx(3.5)
    assert fetched.goals[0].title == goal.title
    assert repository.list_alive_agents()[0].id == created.id


def test_memory_and_world_repositories_persist_records(db_session: Session) -> None:
    """Memory and world repositories should persist domain records without extra boilerplate."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    world_repository = WorldRepository(db_session)

    agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ivo",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=2,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    memory = memory_repository.add_memory(
        EpisodicMemory(
            agent_id=agent.id,
            tick=8,
            event_type="met_neighbor",
            raw_text="Met a new neighbor at the market",
            valence=0.5,
            salience=0.6,
            participant_ids=[agent.id],
        )
    )
    world_event = world_repository.add_world_event(
        WorldEvent(
            tick=8,
            event_type="market_visit",
            actor_ids=[agent.id],
            target_ids=[],
            payload={"stalls": 3},
        )
    )
    inventory = world_repository.add_inventory_entry(
        Inventory(
            owner_type=InventoryOwnerType.AGENT,
            owner_id=agent.id,
            item_type="apple",
            quantity=2,
            metadata_json={"ripe": True},
        )
    )
    db_session.commit()

    assert db_session.scalar(select(EpisodicMemory).where(EpisodicMemory.id == memory.id)) is not None
    assert db_session.scalar(select(WorldEvent).where(WorldEvent.id == world_event.id)) is not None
    assert db_session.scalar(select(Inventory).where(Inventory.id == inventory.id)) is not None


def test_agent_repository_creates_and_queries_relationships(db_session: Session) -> None:
    """The agent repository should create and query directed relationship records."""

    repository = AgentRepository(db_session)
    source = repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=0,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    target = repository.create_agent_bundle(
        AgentCreateParams(
            name="Beck",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )

    created = repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=source.id,
            target_agent_id=target.id,
            familiarity=0.8,
            trust=0.6,
            kinship_type=KinshipType.SIBLING,
            last_interaction_tick=12,
        )
    )
    db_session.commit()

    fetched = repository.get_relationship(source.id, target.id)
    related = repository.list_relationships_for_agent(source.id)

    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.kinship_type is KinshipType.SIBLING
    assert fetched.familiarity == pytest.approx(0.8)
    assert [relationship.id for relationship in related] == [created.id]


def test_agent_repository_creates_and_updates_goals(db_session: Session) -> None:
    """The agent repository should create goals and update them in place."""

    repository = AgentRepository(db_session)
    agent = repository.create_agent_bundle(
        AgentCreateParams(
            name="Caro",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=3,
            stage_of_life=StageOfLife.ADULT,
        )
    )

    created = repository.create_goal(
        GoalCreateParams(
            agent_id=agent.id,
            goal_type=GoalType.SAFETY,
            title="Secure enough food for winter",
            priority=2.5,
            horizon_days=10,
            status=GoalStatus.ACTIVE,
            source=GoalSource.REFLECTION,
            created_tick=25,
            updated_tick=25,
            success_condition={"stored_food": 20},
        )
    )
    updated = repository.update_goal(
        created.id,
        GoalUpdateParams(
            status=GoalStatus.COMPLETED,
            blocker_summary="Resolved after harvest",
            success_condition={"stored_food": 24},
            updated_tick=30,
        ),
    )
    db_session.commit()

    active_goals = repository.list_goals_for_agent(agent.id, status=GoalStatus.ACTIVE)
    all_goals = repository.list_goals_for_agent(agent.id)

    assert updated.id == created.id
    assert updated.status is GoalStatus.COMPLETED
    assert updated.blocker_summary == "Resolved after harvest"
    assert updated.success_condition == {"stored_food": 24}
    assert updated.updated_tick == 30
    assert active_goals == []
    assert [goal.id for goal in all_goals] == [created.id]


def test_memory_repository_creates_and_queries_memories_and_beliefs(db_session: Session) -> None:
    """The memory repository should create episodic memories and semantic beliefs cleanly."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Dane",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=5,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )

    created_memory = memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=agent.id,
            tick=40,
            event_type="harvest_success",
            raw_text="The autumn harvest exceeded expectations.",
            valence=0.9,
            salience=0.95,
            location_x=5,
            location_y=1,
            participant_ids=[agent.id],
        )
    )
    archived_memory = memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=agent.id,
            tick=30,
            event_type="old_story",
            raw_text="An old story from the village square.",
            valence=0.1,
            salience=0.2,
            participant_ids=[],
            archived=True,
        )
    )
    created_belief = memory_repository.create_belief(
        SemanticBeliefCreateParams(
            agent_id=agent.id,
            subject_type="building",
            predicate="is_safe",
            object_value="yes",
            confidence=0.8,
            last_supported_tick=41,
        )
    )
    db_session.commit()

    live_memories = memory_repository.list_memories_for_agent(agent.id)
    all_memories = memory_repository.list_memories_for_agent(agent.id, include_archived=True)
    beliefs = memory_repository.list_beliefs_for_agent(agent.id)

    assert [memory.id for memory in live_memories] == [created_memory.id]
    assert [memory.id for memory in all_memories] == [created_memory.id, archived_memory.id]
    assert [belief.id for belief in beliefs] == [created_belief.id]
    assert beliefs[0].object_value == "yes"


def test_world_repository_creates_world_events_with_payload_and_actor_ids(db_session: Session) -> None:
    """The world repository should create world events through thin parameter helpers."""

    agent_repository = AgentRepository(db_session)
    world_repository = WorldRepository(db_session)
    actor = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Eli",
            sex=AgentSex.INTERSEX,
            birth_tick=0,
            current_tile_x=6,
            current_tile_y=6,
            stage_of_life=StageOfLife.ADULT,
        )
    )

    created = world_repository.create_world_event(
        WorldEventCreateParams(
            tick=55,
            event_type="storm_warning",
            actor_ids=[actor.id],
            target_ids=[],
            location_x=6,
            location_y=6,
            payload={"severity": "high", "wind": 3},
        )
    )
    db_session.commit()

    fetched = db_session.scalar(select(WorldEvent).where(WorldEvent.id == created.id))

    assert fetched is not None
    assert fetched.actor_ids == [actor.id]
    assert fetched.payload == {"severity": "high", "wind": 3}


def test_world_repository_lists_world_events_as_transport_dtos(db_session: Session) -> None:
    """The world repository should expose persisted world events as transport-safe DTOs."""

    agent_repository = AgentRepository(db_session)
    world_repository = WorldRepository(db_session)
    actor = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Gio",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=2,
            stage_of_life=StageOfLife.ADULT,
        )
    )

    world_repository.create_world_event(
        WorldEventCreateParams(
            tick=61,
            event_type="warehouse_fire",
            actor_ids=[actor.id],
            target_ids=[],
            location_x=2,
            location_y=2,
            payload={"severity": "medium"},
        )
    )
    db_session.commit()

    events = world_repository.list_world_events()

    assert len(events) == 1
    assert isinstance(events[0], WorldEventSchema)
    assert events[0].actor_ids == [str(actor.id)]
    assert events[0].payload == {"severity": "medium"}


def test_goal_repository_raises_for_unknown_goal(db_session: Session) -> None:
    """Updating an unknown goal should fail loudly instead of silently doing nothing."""

    repository = AgentRepository(db_session)

    with pytest.raises(LookupError, match="Unknown goal"):
        repository.update_goal(uuid.uuid4(), GoalUpdateParams(status=GoalStatus.ABANDONED, updated_tick=1))


def test_memory_repository_supports_existing_thin_add_methods(db_session: Session) -> None:
    """The original add methods should still work alongside the new create helpers."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Fia",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=3,
            current_tile_y=4,
            stage_of_life=StageOfLife.ADULT,
        )
    )

    belief = memory_repository.add_belief(
        SemanticBelief(
            agent_id=agent.id,
            subject_type="agent",
            subject_id=agent.id,
            predicate="is_reliable",
            object_value="likely",
            confidence=0.7,
            last_supported_tick=9,
        )
    )
    db_session.commit()

    assert db_session.scalar(select(SemanticBelief).where(SemanticBelief.id == belief.id)) is not None
