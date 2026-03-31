"""Simulation runtime and tick-loop orchestration."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from app.agents.executor import ActionExecutor
from app.agents.needs import NeedService
from app.agents.perception import PerceptionService
from app.agents.planner import ActionPlanner
from app.agents.runtime import AgentRuntime
from app.agents.utility_ai import UtilityAI
from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.reflection import ReflectionWorkflow
from app.cognition.reflection_graph import AutobiographyBuilder
from app.cognition.slow_loop import SlowLoopService
from app.cognition.validation import ReflectionValidator
from app.engine.event_bus import EventBus
from app.engine.rules.simulation_rules import is_action_legal
from app.engine.scheduler import TaskScheduler
from app.engine.sim_clock import SimulationClock
from app.engine.world_loop import WorldLoop
from app.engine.world_state import AgentState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.schemas.api import SimulationSnapshot
from app.schemas.event import EventType, SimulationEvent
from app.telemetry.metrics import TelemetryRecorder


class SimulationRuntime:
    """Owns the authoritative world state and advances it over time."""

    def __init__(self, initial_state: WorldState, tick_interval_seconds: float) -> None:
        self._world_state = initial_state
        self._tick_interval_seconds = tick_interval_seconds
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._event_bus = EventBus()
        self._scheduler = TaskScheduler()
        self._telemetry = TelemetryRecorder()
        self._sim_clock = SimulationClock(
            start_time=initial_state.current_time,
            tick_interval=timedelta(seconds=tick_interval_seconds),
        )
        self._slow_loop_service = SlowLoopService(
            memory_retriever=MemoryRetriever(),
            autobiography_builder=AutobiographyBuilder(),
            reflection_workflow=ReflectionWorkflow(),
            validator=ReflectionValidator(),
            goal_updater=GoalUpdater(),
            belief_updater=BeliefUpdater(),
            memory_writer=MemoryWriter(),
        )
        self._agent_runtime = AgentRuntime(
            perception_service=PerceptionService(),
            need_service=NeedService(),
            utility_ai=UtilityAI(),
            planner=ActionPlanner(),
            executor=ActionExecutor(),
            slow_loop_service=self._slow_loop_service,
        )
        self._world_loop = WorldLoop(
            world_state=self._world_state,
            sim_clock=self._sim_clock,
            scheduler=self._scheduler,
            agent_runtime=self._agent_runtime,
            telemetry=self._telemetry,
            event_bus=self._event_bus,
        )

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

    async def emit_simulation_event(
        self,
        event_type: EventType,
        agent_id: str | None = None,
        payload: dict[str, object] | None = None,
    ) -> None:
        """Enqueue an authoritative simulation event for the next world tick."""

        async with self._lock:
            self._event_bus.emit(
                SimulationEvent(
                    type=event_type,
                    tick=self._world_state.tick,
                    sim_time=self._world_state.current_time,
                    agent_id=agent_id,
                    payload=payload or {},
                )
            )

    async def get_debug_state(self) -> dict[str, object]:
        """Return lightweight debug state for the current simulation runtime."""

        async with self._lock:
            return {
                "tick": self._world_state.tick,
                "sim_time": self._world_state.current_time.isoformat(),
                "weather": self._world_state.weather,
                "pending_scheduler_tasks": self._scheduler.pending_task_ids(),
                "last_fast_loop_traces": [
                    {
                        "agent_id": trace.agent_id,
                        "stage_order": list(trace.stage_order),
                        "selected_action": trace.selected_action,
                        "planner_hints_before": list(trace.planner_hints_before),
                        "planner_hints_after": list(trace.planner_hints_after),
                    }
                    for trace in self._agent_runtime.last_step_traces
                ],
                "last_slow_loop_results": [
                    {
                        "agent_id": result.agent_id,
                        "trigger_reasons": list(result.trigger_reasons),
                        "applied": result.applied,
                        "planner_hints": list(result.planner_hints),
                    }
                    for result in self._slow_loop_service.last_results
                ],
                "last_tick_telemetry": (
                    {
                        "tick": self._telemetry.tick_history[-1].tick,
                        "stage_order": list(self._telemetry.tick_history[-1].stage_order),
                        "event_count": self._telemetry.tick_history[-1].event_count,
                        "event_types": list(self._telemetry.tick_history[-1].event_types),
                    }
                    if self._telemetry.tick_history
                    else None
                ),
            }

    def _get_agent(self, agent_id: str) -> AgentState | None:
        """Look up an agent by its authoritative identifier."""

        for agent in self._world_state.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def _step_once_locked(self) -> SimulationSnapshot:
        """Advance one tick while the caller holds the runtime lock."""

        return self._world_loop.tick_once()
