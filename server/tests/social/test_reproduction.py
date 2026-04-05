"""Focused tests for conception, birth, inheritance, and family persistence."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.orm import Session, sessionmaker

from app.agents.lifecycle import LifecycleService
from app.db.base import Base, import_models
from app.db.enums import AgentSex, GoalSource, GoalStatus, GoalType, KinshipType, PregnancyStatus, StageOfLife
from app.db.repositories import AgentCreateParams, AgentRepository, GoalCreateParams
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType
from app.social.bonding import RelationshipMetrics
from app.social.inheritance import TraitInheritanceService
from app.social.reproduction import ReproductionService


@pytest.fixture
def db_session() -> Session:
    """Create an isolated persistence session for reproduction tests."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @sqlalchemy_event.listens_for(engine, "connect")
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


def test_bonded_pair_can_trigger_injectable_conception_and_prevent_duplicates(db_session: Session) -> None:
    """Conception should be probability-driven, persistent-aware, and duplicate-safe."""

    world, resolver = _world_and_resolver(db_session)

    @contextmanager
    def session_scope():
        yield db_session

    service = ReproductionService(
        gestation_ticks=3,
        random_fn=lambda: 0.0,
        session_scope=session_scope,
        resolve_agent_id=resolver.get,
    )
    lifecycle = LifecycleService(gestation_ticks=3)

    result = service.try_conception(
        world,
        world.agents[0],
        world.agents[1],
        tick=5,
        now=_now(),
        event_bus=EventBus(),
        is_fertile=lifecycle.is_fertile,
        start_pregnancy=lifecycle.start_pregnancy,
        relationship=RelationshipMetrics(familiarity=0.8, trust=0.8, attraction=0.8, admiration=0.5),
    )

    persistent_mother = resolver["agent-1"]
    pregnancy = AgentRepository(db_session).get_active_pregnancy(persistent_mother)

    assert result.started is True
    assert result.event is not None
    assert result.event.type is EventType.PREGNANCY_STARTED
    assert result.event.actor_ids == ["agent-1"]
    assert result.event.target_ids == ["agent-2"]
    assert result.event.payload == {"partner_id": "agent-2"}
    assert world.agents[0].pregnancy_progress_ticks == 0
    assert world.agents[0].hunger == pytest.approx(4.0)
    assert world.agents[0].fatigue == pytest.approx(5.0)
    assert world.agents[0].health == pytest.approx(98.0)
    assert world.agents[0].household_planning_pressure == pytest.approx(20.0)
    assert world.agents[1].household_planning_pressure == pytest.approx(10.0)
    assert pregnancy is not None
    assert pregnancy.status is PregnancyStatus.ACTIVE

    duplicate = service.try_conception(
        world,
        world.agents[0],
        world.agents[1],
        tick=6,
        now=_now(),
        event_bus=EventBus(),
        is_fertile=lifecycle.is_fertile,
        start_pregnancy=lifecycle.start_pregnancy,
    )

    assert duplicate.started is False
    assert duplicate.reason == "already_pregnant"


def test_conception_probability_is_deterministic_bounded_and_sensitive_to_inputs() -> None:
    """Conception probability should be explicit, bounded, and higher for stronger pairs."""

    service = ReproductionService()
    mother = AgentState(
        agent_id="agent-1",
        name="Ari",
        x=1,
        y=1,
        sex=AgentSex.FEMALE,
        stage_of_life=StageOfLife.ADULT,
        family_orientation=0.2,
        health=55.0,
    )
    father = AgentState(
        agent_id="agent-2",
        name="Bea",
        x=2,
        y=1,
        sex=AgentSex.MALE,
        stage_of_life=StageOfLife.ADULT,
        family_orientation=0.2,
    )
    low_probability = service.compute_conception_probability(
        mother,
        father,
        relationship=RelationshipMetrics(familiarity=0.3, trust=0.2, attraction=0.2, admiration=0.1),
    )

    mother.family_orientation = 0.9
    mother.health = 100.0
    father.family_orientation = 0.9
    high_probability = service.compute_conception_probability(
        mother,
        father,
        relationship=RelationshipMetrics(familiarity=0.9, trust=1.0, attraction=1.0, admiration=0.8),
    )

    assert low_probability == pytest.approx(
        service.compute_conception_probability(
            mother=AgentState(
                agent_id="agent-1",
                name="Ari",
                x=1,
                y=1,
                sex=AgentSex.FEMALE,
                stage_of_life=StageOfLife.ADULT,
                family_orientation=0.2,
                health=55.0,
            ),
            father=AgentState(
                agent_id="agent-2",
                name="Bea",
                x=2,
                y=1,
                sex=AgentSex.MALE,
                stage_of_life=StageOfLife.ADULT,
                family_orientation=0.2,
            ),
            relationship=RelationshipMetrics(familiarity=0.3, trust=0.2, attraction=0.2, admiration=0.1),
        )
    )
    assert 0.0 <= low_probability <= 0.75
    assert 0.0 <= high_probability <= 0.75
    assert high_probability > low_probability


def test_failed_conception_does_not_create_pregnancy_or_side_effects(db_session: Session) -> None:
    """Failed conception rolls no family state forward and leaves persistence untouched."""

    world, resolver = _world_and_resolver(db_session)

    @contextmanager
    def session_scope():
        yield db_session

    service = ReproductionService(
        gestation_ticks=3,
        random_fn=lambda: 0.99,
        session_scope=session_scope,
        resolve_agent_id=resolver.get,
    )
    lifecycle = LifecycleService(gestation_ticks=3)

    result = service.try_conception(
        world,
        world.agents[0],
        world.agents[1],
        tick=5,
        now=_now(),
        event_bus=EventBus(),
        is_fertile=lifecycle.is_fertile,
        start_pregnancy=lifecycle.start_pregnancy,
        relationship=RelationshipMetrics(familiarity=0.8, trust=0.8, attraction=0.8, admiration=0.5),
    )

    pregnancy = AgentRepository(db_session).get_active_pregnancy(resolver["agent-1"])

    assert result.started is False
    assert result.reason == "conception_missed"
    assert pregnancy is None
    assert world.agents[0].pregnancy_progress_ticks is None
    assert world.agents[0].hunger == pytest.approx(0.0)
    assert world.agents[0].fatigue == pytest.approx(0.0)
    assert world.agents[0].health == pytest.approx(100.0)
    assert world.agents[0].household_planning_pressure == pytest.approx(0.0)
    assert world.agents[1].household_planning_pressure == pytest.approx(0.0)


def test_lifecycle_birth_creates_child_kinship_goals_and_events(db_session: Session) -> None:
    """Lifecycle progression should turn pregnancy into a child plus persistent family state."""

    world, resolver = _world_and_resolver(db_session)

    @contextmanager
    def session_scope():
        yield db_session

    inherited_variation = {"family_orientation": 0.15}
    service = ReproductionService(
        gestation_ticks=2,
        random_fn=lambda: 1.0,
        session_scope=session_scope,
        resolve_agent_id=resolver.get,
        register_agent_id=resolver.__setitem__,
        inheritance_service=TraitInheritanceService(variation_fn=lambda trait_name: inherited_variation.get(trait_name, 0.0)),
    )
    lifecycle = LifecycleService(gestation_ticks=2, reproduction_service=service)
    world.agents[0].pregnancy_progress_ticks = 1
    world.agents[0].pregnancy_partner_id = "agent-2"

    events = lifecycle.update(world, tick=10, now=_now(), event_bus=EventBus())

    repository = AgentRepository(db_session)
    persistent_mother = repository.get_agent_with_related(resolver["agent-1"])
    persistent_father = repository.get_agent_with_related(resolver["agent-2"])
    child_runtime = world.agents[-1]
    persistent_child = repository.get_agent_with_related(resolver[child_runtime.agent_id])
    mother_to_child = repository.get_relationship(persistent_mother.id, persistent_child.id)
    child_to_mother = repository.get_relationship(persistent_child.id, persistent_mother.id)
    father_goals = repository.list_goals_for_agent(persistent_father.id, status=GoalStatus.ACTIVE)
    birth_events = [event for event in events if event.type in {EventType.BIRTH, EventType.CHILD_BORN}]

    assert any(event.type is EventType.CHILD_BORN for event in events)
    assert [event.type for event in birth_events] == [EventType.BIRTH, EventType.CHILD_BORN]
    assert child_runtime.stage_of_life is StageOfLife.INFANT
    assert child_runtime.household_id == "household-1"
    assert child_runtime.parent_ids == ["agent-1", "agent-2"]
    assert child_runtime.family_orientation == pytest.approx(0.8)
    assert world.agents[0].has_infant_care_duty is True
    assert world.agents[1].has_infant_care_duty is True
    assert world.agents[0].current_goal.startswith("Care for ")
    assert persistent_child is not None
    assert persistent_child.stage_of_life is StageOfLife.INFANT
    assert persistent_child.household_id == persistent_mother.household_id
    assert persistent_child.traits.family_orientation == pytest.approx(0.8)
    assert mother_to_child is not None
    assert mother_to_child.kinship_type is KinshipType.PARENT
    assert child_to_mother is not None
    assert child_to_mother.kinship_type is KinshipType.CHILD
    assert {goal.title for goal in father_goals} >= {f"Care for {child_runtime.name}", "Increase household food security"}
    assert {goal.goal_type for goal in father_goals} >= {GoalType.FAMILY, GoalType.SAFETY}
    assert birth_events[0].actor_ids == ["agent-1", "agent-2"]
    assert birth_events[0].target_ids == [child_runtime.agent_id]
    assert birth_events[0].payload == {
        "child_id": child_runtime.agent_id,
        "household_id": "household-1",
        "parent_ids": ["agent-1", "agent-2"],
    }
    assert birth_events[1].payload == birth_events[0].payload


def test_birth_does_not_duplicate_existing_parent_goals(db_session: Session) -> None:
    """Goal seeding should preserve existing active parent goals instead of duplicating them."""

    world, resolver = _world_and_resolver(db_session)

    @contextmanager
    def session_scope():
        yield db_session

    repository = AgentRepository(db_session)
    mother_uuid = resolver["agent-1"]
    father_uuid = resolver["agent-2"]
    repository.create_goal(
        GoalCreateParams(
            agent_id=mother_uuid,
            goal_type=GoalType.FAMILY,
            title="Care for Child 3",
            priority=0.95,
            horizon_days=3,
            status=GoalStatus.ACTIVE,
            source=GoalSource.INHERITED,
            created_tick=9,
            updated_tick=9,
        )
    )
    repository.create_goal(
        GoalCreateParams(
            agent_id=father_uuid,
            goal_type=GoalType.SAFETY,
            title="Increase household food security",
            priority=0.9,
            horizon_days=5,
            status=GoalStatus.ACTIVE,
            source=GoalSource.INHERITED,
            created_tick=9,
            updated_tick=9,
        )
    )
    db_session.commit()

    service = ReproductionService(
        gestation_ticks=2,
        random_fn=lambda: 1.0,
        session_scope=session_scope,
        resolve_agent_id=resolver.get,
        register_agent_id=resolver.__setitem__,
    )
    lifecycle = LifecycleService(gestation_ticks=2, reproduction_service=service)
    world.agents[0].pregnancy_progress_ticks = 1
    world.agents[0].pregnancy_partner_id = "agent-2"

    lifecycle.update(world, tick=10, now=_now(), event_bus=EventBus())

    mother_goals = repository.list_goals_for_agent(mother_uuid, status=GoalStatus.ACTIVE)
    father_goals = repository.list_goals_for_agent(father_uuid, status=GoalStatus.ACTIVE)

    assert [goal.title for goal in mother_goals].count("Care for Child 3") == 1
    assert [goal.title for goal in mother_goals].count("Increase household food security") == 1
    assert [goal.title for goal in father_goals].count("Care for Child 3") == 1
    assert [goal.title for goal in father_goals].count("Increase household food security") == 1


def test_inherited_traits_are_clamped_to_supported_range() -> None:
    """Inheritance should keep newborn trait values inside the supported unit interval."""

    service = TraitInheritanceService(variation_fn=lambda trait_name: 0.4 if trait_name == "family_orientation" else 0.0)

    inherited = service.inherit_runtime_family_orientation(0.9, 0.95)

    assert inherited == pytest.approx(1.0)


def test_persistent_trait_inheritance_is_deterministic_with_partial_parent_traits() -> None:
    """Persistent trait inheritance should fill missing parent values cleanly and stay deterministic."""

    service = TraitInheritanceService(variation_fn=lambda trait_name: 0.05 if trait_name == "family_orientation" else 0.0)

    inherited = service.inherit_persistent_traits(
        {"family_orientation": 0.6, "curiosity": 0.8},
        None,
    )

    assert inherited["family_orientation"] == pytest.approx(0.6)
    assert inherited["curiosity"] == pytest.approx(0.65)
    assert inherited["sociability"] == pytest.approx(0.5)
    assert all(0.0 <= value <= 1.0 for value in inherited.values())


def _world_and_resolver(db_session: Session) -> tuple[WorldState, dict[str, object]]:
    repository = AgentRepository(db_session)
    mother = repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
            household_id=None,
            trait_values={"family_orientation": 0.55},
        )
    )
    father = repository.create_agent_bundle(
        AgentCreateParams(
            name="Bea",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
            household_id=mother.id,
            trait_values={"family_orientation": 0.75},
        )
    )
    mother.household_id = mother.id
    db_session.commit()

    world = WorldState(
        width=5,
        height=5,
        agents=[
            AgentState(
                agent_id="agent-1",
                name="Ari",
                x=1,
                y=1,
                sex=AgentSex.FEMALE,
                partner_id="agent-2",
                household_id="household-1",
                family_orientation=0.55,
            ),
            AgentState(
                agent_id="agent-2",
                name="Bea",
                x=2,
                y=1,
                sex=AgentSex.MALE,
                partner_id="agent-1",
                household_id="household-1",
                family_orientation=0.75,
            ),
        ],
    )
    return world, {"agent-1": mother.id, "agent-2": father.id}


def _now() -> datetime:
    return datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc)
