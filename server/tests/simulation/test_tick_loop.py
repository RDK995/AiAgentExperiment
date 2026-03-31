"""Simulation runtime tests for authoritative tick progression."""

import asyncio

from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import build_initial_world_state


def test_step_once_advances_tick_needs_and_positions() -> None:
    """A simulation tick should deterministically update authoritative state."""

    async def run_test() -> None:
        world = build_initial_world_state(width=8, height=6, initial_agent_count=2)
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=999.0)

        starting_positions = [(agent.x, agent.y) for agent in world.agents]

        first_snapshot = await runtime.step_once()
        second_snapshot = await runtime.step_once()

        assert first_snapshot.tick == 1
        assert second_snapshot.tick == 2

        assert first_snapshot.agents[0].position.x == starting_positions[0][0] - 1
        assert first_snapshot.agents[1].position.x == starting_positions[1][0] + 1
        assert first_snapshot.agents[0].needs.hunger == 1.5
        assert first_snapshot.agents[0].needs.thirst == 2.0
        assert first_snapshot.agents[0].needs.fatigue == 0.75

        assert second_snapshot.agents[0].position.x == starting_positions[0][0]
        assert second_snapshot.agents[1].position.x == starting_positions[1][0]

    asyncio.run(run_test())


def test_get_snapshot_does_not_advance_state() -> None:
    """Reading a snapshot should not mutate the authoritative world."""

    async def run_test() -> None:
        world = build_initial_world_state(width=8, height=6, initial_agent_count=1)
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=999.0)

        snapshot = await runtime.get_snapshot()

        assert snapshot.tick == 0
        assert snapshot.agents[0].position.x == world.agents[0].x
        assert snapshot.agents[0].position.y == world.agents[0].y

    asyncio.run(run_test())
