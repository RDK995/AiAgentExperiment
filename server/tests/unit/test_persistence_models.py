"""Model-level tests for the first persistent simulation data layer."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import create_engine, event, func, select
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
    PairBondState,
    PregnancyStatus,
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
    PairBond,
    Pregnancy,
    Relationship,
    SemanticBelief,
    WorldEvent,
)
from app.db.types import JSONB, UUIDArrayType, Vector1536, pgvector_enabled


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite-backed ORM session for persistence tests."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def test_create_agent_with_one_to_one_records(db_session: Session) -> None:
    """A valid agent should persist alongside traits, needs, and skills."""

    agent = _make_agent(name="Ayla")
    agent.traits = AgentTrait(
        sociability=0.8,
        aggression=0.1,
        conscientiousness=0.7,
        curiosity=0.9,
        family_orientation=0.6,
        risk_tolerance=0.4,
        libido=0.5,
        emotional_stability=0.75,
        memory_fidelity=0.85,
        learning_rate=0.65,
    )
    agent.needs = AgentNeed(
        hunger=10.0,
        thirst=12.0,
        fatigue=22.0,
        warmth=60.0,
        health=90.0,
        stress=15.0,
        loneliness=25.0,
        safety=88.0,
    )
    agent.skills = AgentSkill(
        farming=1.0,
        fishing=2.0,
        gathering=3.0,
        cooking=4.0,
        crafting=5.0,
        caregiving=6.0,
        social=7.0,
    )

    db_session.add(agent)
    db_session.commit()
    db_session.refresh(agent)

    assert agent.id is not None
    assert agent.traits.agent_id == agent.id
    assert agent.needs.agent_id == agent.id
    assert agent.skills.agent_id == agent.id
    assert agent.biography_summary == ""
    assert agent.alive is True


def test_relationship_uniqueness_on_source_target_pair(db_session: Session) -> None:
    """Directed relationships should be unique for a source-target pair."""

    source = _persist_agent_graph(db_session, _make_agent(name="Source"))
    target = _persist_agent_graph(db_session, _make_agent(name="Target"))

    db_session.add(
        Relationship(
            source_agent_id=source.id,
            target_agent_id=target.id,
            familiarity=0.2,
            trust=0.4,
            attraction=0.1,
            resentment=0.0,
            admiration=0.5,
            fear=0.0,
            obligation=0.1,
            dependency=0.0,
            kinship_type=KinshipType.NONE,
        )
    )
    db_session.commit()

    db_session.add(
        Relationship(
            source_agent_id=source.id,
            target_agent_id=target.id,
            familiarity=0.9,
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


def test_foreign_key_enforcement_rejects_orphaned_relationships(db_session: Session) -> None:
    """Relationship rows should fail if they reference agents that do not exist."""

    db_session.add(
        Relationship(
            source_agent_id=uuid.uuid4(),
            target_agent_id=uuid.uuid4(),
            familiarity=0.1,
            trust=0.2,
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


def test_relationship_check_constraints_reject_invalid_relational_states(db_session: Session) -> None:
    """Self-relationships and invalid pair bonds should be blocked by constraints."""

    agent = _persist_agent_graph(db_session, _make_agent(name="Solo"))

    db_session.add(
        Relationship(
            source_agent_id=agent.id,
            target_agent_id=agent.id,
            familiarity=0.1,
            trust=0.2,
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
    db_session.rollback()

    db_session.add(
        PairBond(
            agent_a_id=agent.id,
            agent_b_id=agent.id,
            state=PairBondState.COURTING,
            bond_strength=0.3,
            started_tick=5,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_cascade_delete_removes_agent_owned_records(db_session: Session) -> None:
    """Deleting an agent should cascade to owned one-to-one and one-to-many records."""

    agent = _persist_agent_graph(db_session, _make_agent(name="Cascade"))
    goal = AgentGoal(
        agent_id=agent.id,
        goal_type=GoalType.SAFETY,
        title="Stay safe",
        priority=0.9,
        horizon_days=3,
        status=GoalStatus.ACTIVE,
        success_condition={"safe": True},
        source=GoalSource.SEEDED,
        created_tick=1,
        updated_tick=1,
    )
    memory = EpisodicMemory(
        agent_id=agent.id,
        tick=3,
        event_type="gathered_food",
        raw_text="Gathered berries near the river",
        valence=0.4,
        salience=0.8,
        participant_ids=[agent.id],
    )
    belief = SemanticBelief(
        agent_id=agent.id,
        subject_type="resource",
        predicate="located_at",
        object_value="river",
        confidence=0.7,
        last_supported_tick=3,
    )
    db_session.add_all([goal, memory, belief])
    db_session.commit()

    db_session.delete(agent)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Agent)) == 0
    assert db_session.scalar(select(func.count()).select_from(AgentTrait)) == 0
    assert db_session.scalar(select(func.count()).select_from(AgentNeed)) == 0
    assert db_session.scalar(select(func.count()).select_from(AgentSkill)) == 0
    assert db_session.scalar(select(func.count()).select_from(AgentGoal)) == 0
    assert db_session.scalar(select(func.count()).select_from(EpisodicMemory)) == 0
    assert db_session.scalar(select(func.count()).select_from(SemanticBelief)) == 0


def test_cascade_delete_removes_relationships_for_source_and_target_agents(db_session: Session) -> None:
    """Deleting either side of a relationship should cascade the directed edge."""

    source = _persist_agent_graph(db_session, _make_agent(name="SourceCascade"))
    target = _persist_agent_graph(db_session, _make_agent(name="TargetCascade"))
    relationship = Relationship(
        source_agent_id=source.id,
        target_agent_id=target.id,
        familiarity=0.5,
        trust=0.5,
        attraction=0.0,
        resentment=0.0,
        admiration=0.0,
        fear=0.0,
        obligation=0.0,
        dependency=0.0,
        kinship_type=KinshipType.NONE,
    )
    db_session.add(relationship)
    db_session.commit()

    db_session.delete(target)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(Relationship)) == 0


def test_cascade_delete_removes_memory_embedding_with_memory(db_session: Session) -> None:
    """Deleting an episodic memory should cascade to its embedding record."""

    agent = _persist_agent_graph(db_session, _make_agent(name="Embedded"))
    memory = EpisodicMemory(
        agent_id=agent.id,
        tick=7,
        event_type="notable_event",
        raw_text="Witnessed a falling star.",
        valence=0.3,
        salience=0.8,
        participant_ids=[agent.id],
    )
    db_session.add(memory)
    db_session.commit()

    db_session.add(
        MemoryEmbedding(
            memory_id=memory.id,
            agent_id=agent.id,
            embedding=[0.1, 0.2, 0.3],
        )
    )
    db_session.commit()

    db_session.delete(memory)
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(MemoryEmbedding)) == 0


def test_one_to_one_agent_child_records_reject_duplicate_rows(db_session: Session) -> None:
    """One-to-one child tables should reject multiple rows for the same agent."""

    agent = _persist_agent_graph(db_session, _make_agent(name="UniqueChild"))

    db_session.add(
        AgentNeed(
            agent_id=agent.id,
            hunger=2.0,
            thirst=4.0,
            fatigue=6.0,
            warmth=80.0,
            health=90.0,
            stress=10.0,
            loneliness=12.0,
            safety=88.0,
        )
    )

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_json_and_array_backed_fields_round_trip(db_session: Session) -> None:
    """Portable JSON/UUID-array columns should round-trip cleanly."""

    agent = _persist_agent_graph(db_session, _make_agent(name="RoundTrip"))
    participant_ids = [agent.id, uuid.uuid4()]
    event_actor_ids = [agent.id]
    event_target_ids = [uuid.uuid4()]

    memory = EpisodicMemory(
        agent_id=agent.id,
        tick=12,
        event_type="festival",
        location_x=4,
        location_y=8,
        raw_text="Attended the harvest festival",
        valence=0.9,
        salience=0.75,
        participant_ids=participant_ids,
    )
    world_event = WorldEvent(
        tick=12,
        event_type="harvest_festival",
        actor_ids=event_actor_ids,
        target_ids=event_target_ids,
        payload={"weather": "clear", "attendance": 17},
    )
    inventory = Inventory(
        owner_type=InventoryOwnerType.AGENT,
        owner_id=agent.id,
        item_type="berries",
        quantity=4,
        metadata_json={"quality": "fresh"},
    )
    db_session.add_all([memory, world_event, inventory])
    db_session.commit()
    db_session.expire_all()

    persisted_memory = db_session.get(EpisodicMemory, memory.id)
    persisted_event = db_session.get(WorldEvent, world_event.id)
    persisted_inventory = db_session.get(Inventory, inventory.id)

    assert persisted_memory is not None
    assert persisted_memory.participant_ids == participant_ids
    assert persisted_event is not None
    assert persisted_event.actor_ids == event_actor_ids
    assert persisted_event.target_ids == event_target_ids
    assert persisted_event.payload == {"weather": "clear", "attendance": 17}
    assert persisted_inventory is not None
    assert persisted_inventory.metadata_json == {"quality": "fresh"}


def test_required_fields_fail_when_missing(db_session: Session) -> None:
    """Required ORM columns should fail when null values are provided."""

    agent = _make_agent(name="MissingRequired")
    agent.name = None  # type: ignore[assignment]
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

    with pytest.raises(IntegrityError):
        db_session.commit()


def test_foreign_key_enforcement_rejects_orphan_goal_and_pregnancy_rows(db_session: Session) -> None:
    """Goal and pregnancy rows should fail when parent agent references are missing."""

    db_session.add(
        AgentGoal(
            agent_id=uuid.uuid4(),
            goal_type=GoalType.FAMILY,
            title="Invalid goal",
            priority=1.0,
            horizon_days=2,
            status=GoalStatus.ACTIVE,
            source=GoalSource.SEEDED,
            created_tick=1,
            updated_tick=1,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    db_session.add(
        Pregnancy(
            mother_id=uuid.uuid4(),
            father_id=uuid.uuid4(),
            started_tick=5,
            expected_birth_tick=25,
            status=PregnancyStatus.ACTIVE,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_pair_bond_and_pregnancy_records_create_correctly(db_session: Session) -> None:
    """Pair bonds and pregnancies should persist with their enum-backed states."""

    mother = _persist_agent_graph(db_session, _make_agent(name="Mara", sex=AgentSex.FEMALE))
    father = _persist_agent_graph(db_session, _make_agent(name="Tomas", sex=AgentSex.MALE))

    pair_bond = PairBond(
        agent_a_id=mother.id,
        agent_b_id=father.id,
        state=PairBondState.BONDED,
        bond_strength=0.82,
        started_tick=10,
    )
    pregnancy = Pregnancy(
        mother_id=mother.id,
        father_id=father.id,
        started_tick=25,
        expected_birth_tick=125,
        status=PregnancyStatus.ACTIVE,
    )
    db_session.add_all([pair_bond, pregnancy])
    db_session.commit()

    assert pair_bond.state is PairBondState.BONDED
    assert pair_bond.bond_strength == pytest.approx(0.82)
    assert pregnancy.status is PregnancyStatus.ACTIVE
    assert pregnancy.expected_birth_tick == 125


def test_enum_backed_columns_reject_invalid_values(db_session: Session) -> None:
    """Enum-backed fields should reject invalid values where enforcement exists."""

    agent = _persist_agent_graph(db_session, _make_agent(name="EnumCheck"))

    db_session.add(
        Inventory(
            owner_type="spaceship",  # type: ignore[arg-type]
            owner_id=agent.id,
            item_type="berries",
            quantity=1,
            metadata_json={},
        )
    )

    with pytest.raises((IntegrityError, LookupError, ValueError)):
        db_session.commit()


def test_goal_defaults_and_constraints_behave_correctly(db_session: Session) -> None:
    """Goal defaults should apply and invalid constrained values should fail."""

    agent = _persist_agent_graph(db_session, _make_agent(name="Goalie"))
    valid_goal = AgentGoal(
        agent_id=agent.id,
        goal_type=GoalType.EXPLORATION,
        title="Map the river",
        priority=1.5,
        horizon_days=7,
        status=GoalStatus.ACTIVE,
        source=GoalSource.REFLECTION,
        created_tick=2,
        updated_tick=2,
    )
    db_session.add(valid_goal)
    db_session.commit()
    db_session.refresh(valid_goal)

    assert valid_goal.blocker_summary == ""
    assert valid_goal.success_condition == {}

    db_session.add(
        AgentGoal(
            agent_id=agent.id,
            goal_type=GoalType.SAFETY,
            title="Broken goal",
            priority=0.4,
            horizon_days=-1,
            status=GoalStatus.ACTIVE,
            source=GoalSource.SEEDED,
            created_tick=3,
            updated_tick=3,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()
    db_session.rollback()

    db_session.add(
        AgentGoal(
            agent_id=agent.id,
            goal_type=GoalType.WEALTH,
            title="Impossible goal",
            priority=-0.2,
            horizon_days=1,
            status=GoalStatus.ACTIVE,
            source=GoalSource.SEEDED,
            created_tick=4,
            updated_tick=4,
        )
    )
    with pytest.raises(IntegrityError):
        db_session.commit()


def test_memory_embedding_model_is_wired_for_vector_storage(db_session: Session) -> None:
    """Memory embeddings should round-trip and expose the configured vector type."""

    agent = _persist_agent_graph(db_session, _make_agent(name="Vector"))
    memory = EpisodicMemory(
        agent_id=agent.id,
        tick=5,
        event_type="important_memory",
        raw_text="Saw an unusual comet",
        valence=0.2,
        salience=0.95,
        participant_ids=[agent.id],
    )
    db_session.add(memory)
    db_session.commit()

    embedding = MemoryEmbedding(
        memory_id=memory.id,
        agent_id=agent.id,
        embedding=[0.1, 0.2, 0.3],
    )
    db_session.add(embedding)
    db_session.commit()
    db_session.expire_all()

    persisted_embedding = db_session.get(MemoryEmbedding, memory.id)
    assert persisted_embedding is not None
    assert persisted_embedding.embedding == [0.1, 0.2, 0.3]

    compiled_type = str(MemoryEmbedding.__table__.c.embedding.type.dialect_impl(postgresql.dialect())).lower()
    if pgvector_enabled():
        assert "vector" in compiled_type
    else:
        assert "json" in compiled_type


def test_postgresql_specific_types_compile_to_expected_shapes() -> None:
    """Portable helper types should compile to PostgreSQL-native shapes when targeted there."""

    jsonb_type = str(JSONB.dialect_impl(postgresql.dialect())).lower()
    array_type = str(UUIDArrayType().load_dialect_impl(postgresql.dialect())).lower()
    vector_type = str(Vector1536().load_dialect_impl(postgresql.dialect())).lower()

    assert "jsonb" in jsonb_type
    assert "uuid" in array_type
    assert "array" in array_type
    if pgvector_enabled():
        assert "vector" in vector_type
    else:
        assert "json" in vector_type


def _persist_agent_graph(db_session: Session, agent: Agent) -> Agent:
    """Persist an agent with required one-to-one dependent records."""

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
    """Build a valid agent record for persistence tests."""

    return Agent(
        name=name,
        sex=sex,
        birth_tick=0,
        current_tile_x=2,
        current_tile_y=3,
        stage_of_life=StageOfLife.ADULT,
    )
