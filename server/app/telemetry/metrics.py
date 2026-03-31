"""Prototype telemetry recorder for authoritative simulation ticks."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.engine.event_bus import EventBus
from app.engine.sim_clock import SimTick
from app.schemas.event import EventType, SimulationEvent


@dataclass(slots=True)
class TickTelemetry:
    """Recorded telemetry for a single tick."""

    tick: int
    stage_order: list[str] = field(default_factory=list)
    event_count: int = 0
    event_types: list[str] = field(default_factory=list)


class TelemetryRecorder:
    """Collects deterministic telemetry for debugging and tests."""

    def __init__(self) -> None:
        self.tick_history: list[TickTelemetry] = []
        self._current_stage_order: list[str] = []
        self.last_flushed_events: list[SimulationEvent] = []

    def record_stage(self, stage_name: str) -> None:
        """Record that a stage executed during the current tick."""

        self._current_stage_order.append(stage_name)

    def flush_tick(self, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
        """Emit a telemetry event and persist the per-tick telemetry summary."""

        events = event_bus.drain()
        self.tick_history.append(
            TickTelemetry(
                tick=tick.tick,
                stage_order=list(self._current_stage_order),
                event_count=len(events),
                event_types=[event.type.value for event in events],
            )
        )
        self._current_stage_order.clear()
        telemetry_event = SimulationEvent(
            type=EventType.TELEMETRY,
            tick=tick.tick,
            sim_time=tick.at,
            payload={"event_count": len(events)},
        )
        self.last_flushed_events = [*events, telemetry_event]
        return self.last_flushed_events
