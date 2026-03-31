"""Unit tests for the backend simulation core."""

import asyncio

from app.engine.rules.simulation_rules import is_action_legal, is_movement_valid
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import AgentState, WorldState
from app.schemas.api import SimulationSnapshot


def test_world_tick_progression_advances_authoritative_state(simple_world: WorldState) -> None:
    """A tick should advance time and update the authoritative agent state."""

    async def run_test() -> None:
        runtime = SimulationRuntime(initial_state=simple_world, tick_interval_seconds=999.0)

        before_x = simple_world.agents[0].x
        snapshot = await runtime.step_once()

        assert snapshot.tick == 1
        assert snapshot.agents[0].position.x == before_x - 1
        assert snapshot.agents[0].current_action == "walking"

    asyncio.run(run_test())


def test_agent_need_decay_is_deterministic_and_clamped() -> None:
    """Need decay should follow fixed server-side rules and remain bounded."""

    agent = AgentState(
        agent_id="agent-1",
        name="Villager 1",
        x=0,
        y=0,
        hunger=98.5,
        thirst=97.5,
        fatigue=99.5,
    )

    agent.advance_needs()

    assert agent.hunger == 100.0
    assert agent.thirst == 99.5
    assert agent.fatigue == 100.0


def test_action_legality_allows_adjacent_walkable_move(simple_world: WorldState) -> None:
    """Move actions are legal only for adjacent, walkable destinations."""

    agent = simple_world.agents[0]

    assert is_action_legal(simple_world, agent, action="move", target_x=0, target_y=1) is True


def test_action_legality_rejects_non_adjacent_or_non_walkable_targets(
    simple_world: WorldState,
) -> None:
    """Illegal moves should be rejected by authoritative simulation rules."""

    agent = simple_world.agents[0]

    assert is_action_legal(simple_world, agent, action="move", target_x=3, target_y=1) is False
    assert is_action_legal(simple_world, agent, action="move", target_x=2, target_y=0) is False
    assert is_action_legal(simple_world, agent, action="move", target_x=1, target_y=1) is False
    assert is_action_legal(simple_world, agent, action="dance", target_x=0, target_y=1) is False


def test_movement_validity_checks_bounds_and_walkability(simple_world: WorldState) -> None:
    """Movement validity should reject out-of-bounds and blocked tiles."""

    assert is_movement_valid(simple_world, 0, 1) is True
    assert is_movement_valid(simple_world, 2, 0) is False
    assert is_movement_valid(simple_world, -1, 1) is False
    assert is_movement_valid(simple_world, 4, 1) is False


def test_snapshot_generation_serializes_authoritative_world_state(
    simple_world: WorldState,
) -> None:
    """Snapshots should contain a transport-safe view of current server state."""

    simple_world.tick = 7
    simple_world.agents[0].current_action = "walking"

    snapshot: SimulationSnapshot = simple_world.to_snapshot()

    assert snapshot.tick == 7
    assert snapshot.world.width == 4
    assert snapshot.world.height == 3
    assert len(snapshot.world.tiles) == 12
    assert snapshot.agents[0].agent_id == "agent-1"
    assert snapshot.agents[0].position.x == 1
    assert snapshot.agents[0].position.y == 1
    assert snapshot.agents[0].current_action == "walking"
