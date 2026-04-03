"""Focused tests for deterministic reflection trigger evaluation."""

from __future__ import annotations

from datetime import datetime, timezone

from app.cognition.triggers import ReflectionTriggerEvaluator
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent
from app.schemas.reflection import MemoryCandidate


def test_day_rollover_triggers_all_agents_and_expires_stale_summary_queues() -> None:
    """Day rollover should mark every agent and clear stale daily-summary queues."""

    day_index = datetime(2000, 1, 2, tzinfo=timezone.utc).toordinal()
    world = WorldState(
        width=2,
        height=1,
        day_index=day_index - 1,
        agents=[
            AgentState(
                agent_id="agent-1",
                name="A",
                x=0,
                y=0,
                daily_summary_day_index=day_index - 1,
                daily_summary_candidates=[MemoryCandidate(text="old", salience=0.9, valence=0.1)],
            ),
            AgentState(agent_id="agent-2", name="B", x=1, y=0),
        ],
    )

    ReflectionTriggerEvaluator().apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.DAY_ROLLOVER,
            tick=1,
            sim_time=datetime(2000, 1, 2, 0, 0, tzinfo=timezone.utc),
            payload={"day_index": day_index},
        ),
    )

    assert [sorted(agent.slow_loop_trigger_flags) for agent in world.agents] == [["day_rollover"], ["day_rollover"]]
    assert world.agents[0].daily_summary_day_index == day_index
    assert world.agents[0].daily_summary_candidates == []


def test_birth_in_household_triggers_parent_household_and_partner() -> None:
    """Childbirth should trigger close household reflection, not unrelated villagers."""

    world = WorldState(
        width=3,
        height=1,
        agents=[
            AgentState(agent_id="agent-1", name="Parent", x=0, y=0, household_id="house-1", partner_id="agent-2"),
            AgentState(agent_id="agent-2", name="Partner", x=1, y=0, household_id="house-1", partner_id="agent-1"),
            AgentState(agent_id="agent-3", name="Sibling", x=2, y=0, household_id="house-1"),
            AgentState(agent_id="agent-4", name="Other", x=2, y=0, household_id="house-2"),
        ],
    )

    ReflectionTriggerEvaluator().apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.CHILD_BORN,
            tick=4,
            sim_time=datetime(2000, 1, 1, 9, 0, tzinfo=timezone.utc),
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-5"],
            payload={"child_id": "agent-5"},
        ),
    )

    assert "birth_in_household" in world.agents[0].slow_loop_trigger_flags
    assert "birth_in_household" in world.agents[1].slow_loop_trigger_flags
    assert "birth_in_household" in world.agents[2].slow_loop_trigger_flags
    assert world.agents[3].slow_loop_trigger_flags == set()


def test_death_of_close_relation_triggers_only_close_relations() -> None:
    """Deaths should trigger partners and household members but not unrelated agents."""

    world = WorldState(
        width=3,
        height=1,
        agents=[
            AgentState(agent_id="agent-1", name="Deceased", x=0, y=0, household_id="house-1", partner_id="agent-2"),
            AgentState(agent_id="agent-2", name="Partner", x=1, y=0, household_id="house-1", partner_id="agent-1"),
            AgentState(agent_id="agent-3", name="Housemate", x=2, y=0, household_id="house-1"),
            AgentState(agent_id="agent-4", name="Other", x=2, y=0, household_id="house-2"),
        ],
    )

    ReflectionTriggerEvaluator().apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.AGENT_DIED,
            tick=9,
            sim_time=datetime(2000, 1, 1, 10, 0, tzinfo=timezone.utc),
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"kind": "health_failure"},
        ),
    )

    assert "death_of_close_relation" in world.agents[1].slow_loop_trigger_flags
    assert "death_of_close_relation" in world.agents[2].slow_loop_trigger_flags
    assert world.agents[3].slow_loop_trigger_flags == set()


def test_repeated_plan_failure_and_severe_need_triggers_are_deterministic() -> None:
    """State and plan-failure triggers should activate once thresholds are crossed."""

    world = WorldState(
        width=1,
        height=1,
        agents=[
            AgentState(
                agent_id="agent-1",
                name="A",
                x=0,
                y=0,
                hunger=92.0,
                health=24.0,
                plan_failure_count=3,
            )
        ],
    )
    evaluator = ReflectionTriggerEvaluator()
    evaluator.apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.PLAN_FAILED,
            tick=3,
            sim_time=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"attempted_goal": "Store food"},
        ),
    )
    evaluator.apply_state_triggers(world)

    assert world.agents[0].slow_loop_trigger_flags == {"repeated_plan_failure", "severe_hunger_or_injury"}


def test_major_gift_and_betrayal_trigger_involved_agents_only() -> None:
    """Major gifts and betrayal-like insults should only trigger participating agents."""

    world = WorldState(
        width=3,
        height=1,
        agents=[
            AgentState(agent_id="agent-1", name="A", x=0, y=0),
            AgentState(agent_id="agent-2", name="B", x=1, y=0),
            AgentState(agent_id="agent-3", name="C", x=2, y=0),
        ],
    )
    evaluator = ReflectionTriggerEvaluator()
    evaluator.apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.GIFT_GIVEN,
            tick=5,
            sim_time=datetime(2000, 1, 1, 11, 0, tzinfo=timezone.utc),
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"major_gift": True},
        ),
    )
    evaluator.apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.INSULT_SPOKEN,
            tick=6,
            sim_time=datetime(2000, 1, 1, 11, 5, tzinfo=timezone.utc),
            agent_id="agent-2",
            actor_ids=["agent-2"],
            target_ids=["agent-1"],
            payload={"betrayal": True},
        ),
    )

    assert world.agents[0].slow_loop_trigger_flags == {"major_gift", "betrayal"}
    assert world.agents[1].slow_loop_trigger_flags == {"major_gift", "betrayal"}
    assert world.agents[2].slow_loop_trigger_flags == set()


def test_bond_proposal_acceptance_and_rejection_trigger_participants_only() -> None:
    """Accepted and rejected bond proposals should trigger only the involved agents."""

    world = WorldState(
        width=4,
        height=1,
        agents=[
            AgentState(agent_id="agent-1", name="A", x=0, y=0),
            AgentState(agent_id="agent-2", name="B", x=1, y=0),
            AgentState(agent_id="agent-3", name="C", x=2, y=0),
            AgentState(agent_id="agent-4", name="D", x=3, y=0),
        ],
    )
    evaluator = ReflectionTriggerEvaluator()
    evaluator.apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.PROPOSAL_ACCEPTED,
            tick=7,
            sim_time=datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc),
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={},
        ),
    )
    evaluator.apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.PROPOSAL_MADE,
            tick=8,
            sim_time=datetime(2000, 1, 1, 12, 5, tzinfo=timezone.utc),
            agent_id="agent-3",
            actor_ids=["agent-3"],
            target_ids=["agent-4"],
            payload={"outcome": "rejected"},
        ),
    )

    assert world.agents[0].slow_loop_trigger_flags == {"bond_proposal_decision"}
    assert world.agents[1].slow_loop_trigger_flags == {"bond_proposal_decision"}
    assert world.agents[2].slow_loop_trigger_flags == {"bond_proposal_decision"}
    assert world.agents[3].slow_loop_trigger_flags == {"bond_proposal_decision"}


def test_ordinary_events_do_not_trigger_reflection_flags() -> None:
    """Routine events should not accidentally mark agents for reflection."""

    world = WorldState(
        width=2,
        height=1,
        agents=[
            AgentState(agent_id="agent-1", name="A", x=0, y=0),
            AgentState(agent_id="agent-2", name="B", x=1, y=0),
        ],
    )

    ReflectionTriggerEvaluator().apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.AGENT_DRANK,
            tick=2,
            sim_time=datetime(2000, 1, 1, 8, 30, tzinfo=timezone.utc),
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"source": "well"},
        ),
    )

    assert world.agents[0].slow_loop_trigger_flags == set()
    assert world.agents[1].slow_loop_trigger_flags == set()


def test_threshold_edges_and_dead_agents_behave_consistently() -> None:
    """Exact trigger thresholds should fire, sub-threshold values should not, and dead agents should be skipped."""

    world = WorldState(
        width=3,
        height=1,
        agents=[
            AgentState(
                agent_id="agent-1",
                name="Exact",
                x=0,
                y=0,
                hunger=90.0,
                health=25.0,
                plan_failure_count=3,
            ),
            AgentState(
                agent_id="agent-2",
                name="Below",
                x=1,
                y=0,
                hunger=89.9,
                health=25.1,
                plan_failure_count=2,
            ),
            AgentState(
                agent_id="agent-3",
                name="Dead",
                x=2,
                y=0,
                hunger=100.0,
                health=0.0,
                alive=False,
            ),
        ],
    )
    evaluator = ReflectionTriggerEvaluator()
    evaluator.apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.PLAN_FAILED,
            tick=10,
            sim_time=datetime(2000, 1, 1, 13, 0, tzinfo=timezone.utc),
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"attempted_goal": "Store food"},
        ),
    )
    evaluator.apply_event_trigger(
        world,
        SimulationEvent(
            type=EventType.PLAN_FAILED,
            tick=11,
            sim_time=datetime(2000, 1, 1, 13, 5, tzinfo=timezone.utc),
            agent_id="agent-2",
            actor_ids=["agent-2"],
            payload={"attempted_goal": "Store food"},
        ),
    )
    evaluator.apply_state_triggers(world)

    assert world.agents[0].slow_loop_trigger_flags == {"repeated_plan_failure", "severe_hunger_or_injury"}
    assert world.agents[1].slow_loop_trigger_flags == set()
    assert world.agents[2].slow_loop_trigger_flags == set()
    assert world.agents[1].slow_loop_trigger_flags == set()
