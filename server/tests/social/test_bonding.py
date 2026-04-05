"""Focused tests for pair-bond eligibility, scoring, and proposal outcomes."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

import pytest
from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.enums import AgentSex, PairBondState, StageOfLife
from app.db.repositories import AgentCreateParams, AgentRepository, RelationshipCreateParams
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType
from app.social.bonding import BondingService, RelationshipMetrics


@pytest.fixture
def db_session() -> Session:
    """Create an isolated persistence session for social-system tests."""

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


def test_bonding_eligibility_requires_adult_alive_socially_available_agents() -> None:
    """Adult living agents with sufficient relationship values and opportunity may bond."""

    world = _world()
    service = BondingService()
    relationship = RelationshipMetrics(familiarity=0.6, trust=0.7, attraction=0.8, admiration=0.4)

    assert service.can_attempt_bond(world.agents[0], world.agents[1], relationship, world=world, tick=10) is True

    world.agents[0].stage_of_life = StageOfLife.ADOLESCENT
    assert service.can_attempt_bond(world.agents[0], world.agents[1], relationship, world=world, tick=10) is False

    world = _world()
    world.agents[0].alive = False
    assert service.can_attempt_bond(world.agents[0], world.agents[1], relationship, world=world, tick=10) is False

    world = _world()
    world.agents[0].bond_rejection_until_tick = 12
    assert service.can_attempt_bond(world.agents[0], world.agents[1], relationship, world=world, tick=10) is False

    world = _world()
    low_attraction = RelationshipMetrics(familiarity=0.6, trust=0.7, attraction=0.2, admiration=0.4)
    assert service.can_attempt_bond(world.agents[0], world.agents[1], low_attraction, world=world, tick=10) is False

    world = _world()
    low_trust = RelationshipMetrics(familiarity=0.6, trust=0.2, attraction=0.8, admiration=0.4)
    assert service.can_attempt_bond(world.agents[0], world.agents[1], low_trust, world=world, tick=10) is False

    world = _world()
    low_familiarity = RelationshipMetrics(familiarity=0.1, trust=0.7, attraction=0.8, admiration=0.4)
    assert service.can_attempt_bond(world.agents[0], world.agents[1], low_familiarity, world=world, tick=10) is False

    world = _world()
    world.agents[1].x = 9
    world.agents[1].y = 9
    assert service.can_attempt_bond(world.agents[0], world.agents[1], relationship, world=world, tick=10) is False

    world = _world()
    assert service.can_attempt_bond(world.agents[0], world.agents[1], None, world=world, tick=10) is False


def test_bond_score_matches_expected_formula_and_availability_bonus() -> None:
    """Bond scoring should be deterministic and follow the documented weight rule."""

    world = _world()
    service = BondingService()
    relationship = RelationshipMetrics(familiarity=0.5, trust=0.8, attraction=0.9, admiration=0.4)

    availability_bonus = service.compute_availability_bonus(world.agents[0], world.agents[1], world)
    score = service.compute_bond_score(
        relationship,
        family_orientation=0.7,
        availability_bonus=availability_bonus,
    )

    expected = round((0.9 * 0.35) + (0.8 * 0.25) + (0.4 * 0.10) + (0.7 * 0.15) + (0.8 * 0.15), 4)
    assert availability_bonus == pytest.approx(0.8)
    assert score == pytest.approx(expected)

    farther_world = _world()
    farther_world.agents[1].x = 5
    farther_score = service.compute_bond_score(
        relationship,
        family_orientation=0.7,
        availability_bonus=service.compute_availability_bonus(farther_world.agents[0], farther_world.agents[1], farther_world),
    )
    assert farther_score < score


def test_bond_score_increases_monotonically_with_each_weighted_input() -> None:
    """Each weighted score component should increase the final bond score when raised in isolation."""

    service = BondingService()
    baseline = service.compute_bond_score(
        RelationshipMetrics(familiarity=0.6, trust=0.4, attraction=0.4, admiration=0.2),
        family_orientation=0.4,
        availability_bonus=0.2,
    )

    higher_attraction = service.compute_bond_score(
        RelationshipMetrics(familiarity=0.6, trust=0.4, attraction=0.8, admiration=0.2),
        family_orientation=0.4,
        availability_bonus=0.2,
    )
    higher_trust = service.compute_bond_score(
        RelationshipMetrics(familiarity=0.6, trust=0.8, attraction=0.4, admiration=0.2),
        family_orientation=0.4,
        availability_bonus=0.2,
    )
    higher_admiration = service.compute_bond_score(
        RelationshipMetrics(familiarity=0.6, trust=0.4, attraction=0.4, admiration=0.8),
        family_orientation=0.4,
        availability_bonus=0.2,
    )
    higher_family_orientation = service.compute_bond_score(
        RelationshipMetrics(familiarity=0.6, trust=0.4, attraction=0.4, admiration=0.2),
        family_orientation=0.8,
        availability_bonus=0.2,
    )
    higher_availability = service.compute_bond_score(
        RelationshipMetrics(familiarity=0.6, trust=0.4, attraction=0.4, admiration=0.2),
        family_orientation=0.4,
        availability_bonus=0.8,
    )

    assert higher_attraction > baseline
    assert higher_trust > baseline
    assert higher_admiration > baseline
    assert higher_family_orientation > baseline
    assert higher_availability > baseline


def test_bond_score_is_clamped_to_supported_bounds() -> None:
    """Extreme inputs should still produce a bounded unit score."""

    service = BondingService()

    high_score = service.compute_bond_score(
        RelationshipMetrics(familiarity=1.0, trust=1.0, attraction=1.0, admiration=1.0),
        family_orientation=1.0,
        availability_bonus=1.0,
    )
    low_score = service.compute_bond_score(
        RelationshipMetrics(familiarity=0.0, trust=0.0, attraction=0.0, admiration=0.0),
        family_orientation=0.0,
        availability_bonus=0.0,
    )

    assert high_score == pytest.approx(1.0)
    assert low_score == pytest.approx(0.0)


def test_eligible_high_score_pair_forms_bond_and_persists_pair_bond(db_session: Session) -> None:
    """Accepted proposals should set partner ids, emit events, and persist a pair bond when configured."""

    repository = AgentRepository(db_session)
    persistent_a = repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=0,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    persistent_b = repository.create_agent_bundle(
        AgentCreateParams(
            name="Bea",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    resolver = {"agent-1": persistent_a.id, "agent-2": persistent_b.id}
    service = BondingService(session_factory=session_scope, resolve_agent_id=resolver.get)
    world = _world()
    bus = EventBus()

    result = service.attempt_bond(
        world.agents[0],
        world.agents[1],
        RelationshipMetrics(familiarity=0.8, trust=0.8, attraction=0.9, admiration=0.6),
        RelationshipMetrics(familiarity=0.8, trust=0.75, attraction=0.85, admiration=0.5),
        world=world,
        tick=20,
        now=_now(),
        event_bus=bus,
    )

    pair_bond = repository.get_pair_bond_between(persistent_a.id, persistent_b.id)

    assert result.attempted is True
    assert result.accepted is True
    assert world.agents[0].partner_id == "agent-2"
    assert world.agents[1].partner_id == "agent-1"
    assert [event.type for event in result.events or []] == [EventType.PROPOSAL_MADE, EventType.PROPOSAL_ACCEPTED]
    assert result.events is not None
    assert result.events[0].actor_ids == ["agent-1"]
    assert result.events[0].target_ids == ["agent-2"]
    assert result.events[0].payload == {"bond_score": result.bond_score}
    assert result.events[1].actor_ids == ["agent-1"]
    assert result.events[1].target_ids == ["agent-2"]
    assert result.events[1].payload == {
        "bond_score": result.bond_score,
        "reciprocal_score": result.reciprocal_score,
    }
    assert pair_bond is not None
    assert pair_bond.state is PairBondState.BONDED
    assert pair_bond.bond_strength > 0.0


def test_rejected_bond_attempt_applies_cooldown_without_creating_pair_bond(db_session: Session) -> None:
    """Rejected proposals should apply cooldown and leave pair-bond persistence empty."""

    repository = AgentRepository(db_session)
    persistent_a = repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=0,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    persistent_b = repository.create_agent_bundle(
        AgentCreateParams(
            name="Bea",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    resolver = {"agent-1": persistent_a.id, "agent-2": persistent_b.id}
    service = BondingService(session_factory=session_scope, resolve_agent_id=resolver.get)
    world = _world()

    result = service.attempt_bond(
        world.agents[0],
        world.agents[1],
        RelationshipMetrics(familiarity=0.8, trust=0.75, attraction=0.85, admiration=0.5),
        RelationshipMetrics(familiarity=0.2, trust=0.1, attraction=0.2, admiration=0.0),
        world=world,
        tick=15,
        now=_now(),
        event_bus=EventBus(),
    )

    assert result.attempted is True
    assert result.accepted is False
    assert result.reason == "proposal_rejected"
    assert world.agents[0].bond_rejection_until_tick == 21
    assert repository.get_pair_bond_between(persistent_a.id, persistent_b.id) is None


def test_social_opportunity_window_triggers_bond_attempt_from_persistent_relationships(db_session: Session) -> None:
    """Lifecycle-facing social opportunity evaluation should emit proposal events and form a bond."""

    repository = AgentRepository(db_session)
    persistent_a = repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    persistent_b = repository.create_agent_bundle(
        AgentCreateParams(
            name="Bea",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=persistent_a.id,
            target_agent_id=persistent_b.id,
            familiarity=0.8,
            trust=0.85,
            attraction=0.9,
            admiration=0.6,
            last_interaction_tick=5,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=persistent_b.id,
            target_agent_id=persistent_a.id,
            familiarity=0.8,
            trust=0.8,
            attraction=0.88,
            admiration=0.55,
            last_interaction_tick=5,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    world = _world()
    bus = EventBus()
    service = BondingService(session_factory=session_scope, resolve_agent_id={"agent-1": persistent_a.id, "agent-2": persistent_b.id}.get)

    events = service.evaluate_social_opportunities(world, tick=7, now=_now(), event_bus=bus)

    assert [event.type for event in events] == [EventType.PROPOSAL_MADE, EventType.PROPOSAL_ACCEPTED]
    assert world.agents[0].partner_id == "agent-2"
    assert world.agents[1].partner_id == "agent-1"
    assert repository.get_pair_bond_between(persistent_a.id, persistent_b.id) is not None


def test_already_bonded_pair_is_not_reproposed_during_later_social_windows(db_session: Session) -> None:
    """Mutually bonded partners should not emit repeat proposal events on later lifecycle windows."""

    repository = AgentRepository(db_session)
    persistent_a = repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    persistent_b = repository.create_agent_bundle(
        AgentCreateParams(
            name="Bea",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=persistent_a.id,
            target_agent_id=persistent_b.id,
            familiarity=0.8,
            trust=0.85,
            attraction=0.9,
            admiration=0.6,
            last_interaction_tick=5,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=persistent_b.id,
            target_agent_id=persistent_a.id,
            familiarity=0.8,
            trust=0.8,
            attraction=0.88,
            admiration=0.55,
            last_interaction_tick=5,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    world = _world()
    world.agents[0].partner_id = "agent-2"
    world.agents[1].partner_id = "agent-1"
    service = BondingService(session_factory=session_scope, resolve_agent_id={"agent-1": persistent_a.id, "agent-2": persistent_b.id}.get)

    events = service.evaluate_social_opportunities(world, tick=8, now=_now(), event_bus=EventBus())

    assert events == []


def _world() -> WorldState:
    return WorldState(
        width=10,
        height=10,
        agents=[
            AgentState(agent_id="agent-1", name="Ari", x=1, y=1, sex=AgentSex.FEMALE, family_orientation=0.7),
            AgentState(agent_id="agent-2", name="Bea", x=2, y=1, sex=AgentSex.MALE, family_orientation=0.6),
        ],
    )


def _now() -> datetime:
    return datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc)
