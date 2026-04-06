"""Authoritative world-loop orchestrator."""

from __future__ import annotations

from app.agents.runtime import AgentRuntime
from app.engine.event_bus import EventBus
from app.engine.scheduler import TaskScheduler
from app.engine.sim_clock import SimTick, SimulationClock
from app.engine.world_state import WorldState
from app.schemas.api import SimulationSnapshot
from app.schemas.event import EventType, SimulationEvent
from app.telemetry.metrics import TelemetryRecorder
from app.telemetry.observability import DailyMetricsCollector


class WorldLoop:
    """Coordinates the authoritative world tick and subsystem ordering."""

    def __init__(
        self,
        world_state: WorldState,
        sim_clock: SimulationClock,
        scheduler: TaskScheduler,
        agent_runtime: AgentRuntime,
        telemetry: TelemetryRecorder,
        event_bus: EventBus,
        daily_metrics: DailyMetricsCollector | None = None,
    ) -> None:
        self._world_state = world_state
        self._sim_clock = sim_clock
        self._scheduler = scheduler
        self._agent_runtime = agent_runtime
        self._telemetry = telemetry
        self._event_bus = event_bus
        self._daily_metrics = daily_metrics

    def tick_once(self) -> SimulationSnapshot:
        """Advance the entire authoritative world by one tick."""

        tick = self._sim_clock.advance()
        if tick.day_rolled_over and self._daily_metrics is not None:
            self._daily_metrics.finalize_day(
                self._world_state,
                day_index=tick.previous_day_index,
                finalized_at=tick.at,
                next_day_index=tick.day_index,
            )
        self._world_state.tick = tick.tick
        self._world_state.current_time = tick.at
        self._world_state.day_index = tick.day_index

        self._telemetry.record_stage("clock.advance")
        self._world_state.update_weather(tick.at)
        self._telemetry.record_stage("world.update_weather")

        self._world_state.update_resources(tick.at)
        self._telemetry.record_stage("world.update_resources")

        self._world_state.update_crops(tick.at)
        self._telemetry.record_stage("world.update_crops")

        if tick.day_rolled_over:
            self._event_bus.emit(
                SimulationEvent(
                    type=EventType.DAY_ROLLOVER,
                    tick=tick.tick,
                    sim_time=tick.at,
                    source_module="world_loop",
                    payload={"day_index": tick.day_index},
                )
            )

        self._scheduler.dispatch_due_tasks(tick.at, self._event_bus)
        self._telemetry.record_stage("scheduler.dispatch_due_tasks")

        self._agent_runtime.step_all(self._world_state, tick, self._event_bus)
        self._telemetry.record_stage("agent_runtime.step_all")

        self._telemetry.flush_tick(tick, self._event_bus)
        return self._world_state.to_snapshot()
