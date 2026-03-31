"""Simulation runtime and tick-loop orchestration."""

from __future__ import annotations

import asyncio
from app.engine.rules.simulation_rules import is_action_legal
from app.engine.world_state import AgentState, WorldState
from app.schemas.api import SimulationSnapshot


class SimulationRuntime:
    """Owns the authoritative world state and advances it over time."""

    def __init__(self, initial_state: WorldState, tick_interval_seconds: float) -> None:
        self._world_state = initial_state
        self._tick_interval_seconds = tick_interval_seconds
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._running = False

    async def start(self) -> None:
        """Start the background tick loop if it is not already running."""

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="simulation-tick-loop")

    async def stop(self) -> None:
        """Stop the background tick loop and wait for shutdown."""

        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        """Advance the simulation on a fixed interval."""

        while self._running:
            await asyncio.sleep(self._tick_interval_seconds)
            await self.step_once()

    async def step_once(self) -> SimulationSnapshot:
        """Advance the authoritative state by one tick and return the snapshot."""

        async with self._lock:
            return self._step_once_locked()

    async def get_snapshot(self) -> SimulationSnapshot:
        """Return a consistent snapshot of current authoritative state."""

        async with self._lock:
            return self._world_state.to_snapshot()

    async def run_for_ticks(self, ticks: int) -> SimulationSnapshot:
        """Advance the simulation by a fixed number of authoritative ticks."""

        async with self._lock:
            latest_snapshot: SimulationSnapshot | None = None
            for _ in range(ticks):
                latest_snapshot = self._step_once_locked()
            assert latest_snapshot is not None
            return latest_snapshot

    async def move_agent(self, agent_id: str, target_x: int, target_y: int) -> SimulationSnapshot:
        """Apply an authoritative movement action if it is legal."""

        async with self._lock:
            agent = self._get_agent(agent_id)
            if agent is None:
                raise LookupError(f"Unknown agent '{agent_id}'.")

            if not is_action_legal(
                self._world_state,
                agent,
                action="move",
                target_x=target_x,
                target_y=target_y,
            ):
                raise ValueError("Illegal move for current world state.")

            agent.x = target_x
            agent.y = target_y
            agent.current_action = "walking"
            return self._world_state.to_snapshot()

    def _advance_agents(self) -> None:
        """Apply deterministic placeholder simulation rules for each agent."""

        for index, agent in enumerate(self._world_state.agents):
            agent.advance_needs()
            direction = 1 if (self._world_state.tick + index) % 2 == 0 else -1
            next_x = agent.x + direction
            if is_action_legal(
                self._world_state,
                agent,
                action="move",
                target_x=next_x,
                target_y=agent.y,
            ):
                agent.x = next_x
                agent.current_action = "walking"
            else:
                agent.current_action = "idle"

    def _get_agent(self, agent_id: str) -> AgentState | None:
        """Look up an agent by its authoritative identifier."""

        for agent in self._world_state.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def _step_once_locked(self) -> SimulationSnapshot:
        """Advance one tick while the caller holds the runtime lock."""

        self._world_state.tick += 1
        self._advance_agents()
        return self._world_state.to_snapshot()
