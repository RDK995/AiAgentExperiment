"""Focused tests for deterministic lifecycle progression."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.lifecycle import LifecycleService
from app.db.enums import AgentSex, StageOfLife
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, TerrainType, TileState, WorldState
from app.schemas.event import EventType


def test_lifecycle_updates_stage_of_life_from_age_progression() -> None:
    """Age progression should update the stage of life deterministically."""

    world = _make_world(
        AgentState(
            agent_id="agent-1",
            name="A",
            x=0,
            y=0,
            age_ticks=999,
            stage_of_life=StageOfLife.ADOLESCENT,
        )
    )

    LifecycleService().update(world, tick=1, now=_now(), event_bus=EventBus())

    assert world.agents[0].stage_of_life is StageOfLife.ADULT


def test_lifecycle_fertility_and_birth_path_are_deterministic() -> None:
    """Fertile adults should progress pregnancy toward a birth event."""

    parent = AgentState(
        agent_id="agent-1",
        name="Parent",
        x=0,
        y=0,
        sex=AgentSex.FEMALE,
        age_ticks=2_000,
        stage_of_life=StageOfLife.ADULT,
    )
    world = _make_world(parent)
    service = LifecycleService(gestation_ticks=2)
    bus = EventBus()

    assert service.is_fertile(parent) is True
    service.start_pregnancy(parent, partner_id="agent-2")
    service.update(world, tick=1, now=_now(), event_bus=bus)
    events = service.update(world, tick=2, now=_now(), event_bus=bus)

    assert any(event.type is EventType.BIRTH for event in events)
    assert len(world.agents) == 2
    assert world.agents[1].stage_of_life is StageOfLife.INFANT


def test_lifecycle_death_marks_agent_and_emits_event() -> None:
    """Agents that hit zero health should die and emit a lifecycle event."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, health=0.0)
    world = _make_world(agent)

    events = LifecycleService().update(world, tick=1, now=_now(), event_bus=EventBus())

    assert agent.alive is False
    assert agent.current_action == "dead"
    assert any(event.type is EventType.DEATH for event in events)


def test_lifecycle_rejects_ineligible_pregnancy_start() -> None:
    """Non-fertile agents should fail cleanly when pregnancy is requested."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        sex=AgentSex.MALE,
        health=100.0,
        age_ticks=2_000,
        stage_of_life=StageOfLife.ADULT,
    )

    service = LifecycleService()

    assert service.is_fertile(agent) is False

    try:
        service.start_pregnancy(agent, partner_id="agent-2")
    except ValueError as exc:
        assert "not fertile" in str(exc)
    else:
        raise AssertionError("Expected pregnancy start to fail for an ineligible agent.")


def test_dead_agents_do_not_continue_normal_lifecycle_progression() -> None:
    """Already-dead agents should not age, emit lifecycle events, or change state further."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        alive=False,
        age_ticks=250,
        stage_of_life=StageOfLife.CHILD,
        pregnancy_progress_ticks=1,
    )
    world = _make_world(agent)

    events = LifecycleService(gestation_ticks=2).update(world, tick=1, now=_now(), event_bus=EventBus())

    assert agent.age_ticks == 250
    assert agent.stage_of_life is StageOfLife.CHILD
    assert agent.pregnancy_progress_ticks == 1
    assert events == []


def test_lifecycle_emits_major_life_event_on_stage_transition() -> None:
    """Stage changes should emit an explicit lifecycle event for downstream consumers."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        age_ticks=99,
        stage_of_life=StageOfLife.INFANT,
    )
    world = _make_world(agent)

    events = LifecycleService().update(world, tick=1, now=_now(), event_bus=EventBus())

    assert agent.stage_of_life is StageOfLife.CHILD
    assert any(event.type is EventType.MAJOR_LIFE_EVENT for event in events)


def test_lifecycle_extreme_needs_reduce_health_before_death_threshold() -> None:
    """Extreme survival needs should degrade health deterministically before causing death."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        hunger=95.0,
        thirst=20.0,
        fatigue=20.0,
        health=50.0,
    )
    world = _make_world(agent)

    LifecycleService().update(world, tick=1, now=_now(), event_bus=EventBus())

    assert agent.health == 48.0
    assert agent.alive is True


def test_birth_clears_pregnancy_state_and_inherits_household() -> None:
    """Birth should reset parent pregnancy state and create a child in the parent's household."""

    parent = AgentState(
        agent_id="agent-1",
        name="Parent",
        x=0,
        y=0,
        sex=AgentSex.FEMALE,
        age_ticks=2_000,
        stage_of_life=StageOfLife.ADULT,
        household_id="household-1",
    )
    world = _make_world(parent)
    service = LifecycleService(gestation_ticks=1)

    service.start_pregnancy(parent, partner_id="agent-2")
    events = service.update(world, tick=1, now=_now(), event_bus=EventBus())

    child = world.agents[1]
    assert any(event.type is EventType.BIRTH for event in events)
    assert parent.pregnancy_progress_ticks is None
    assert parent.pregnancy_partner_id is None
    assert child.household_id == "household-1"


def _make_world(agent: AgentState) -> WorldState:
    """Build a compact world for lifecycle tests."""

    return WorldState(
        width=2,
        height=2,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(2) for x in range(2)],
        agents=[agent],
    )


def _now() -> datetime:
    """Provide a deterministic lifecycle timestamp."""

    return datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc)
