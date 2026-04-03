"""Prototype telemetry recorder for authoritative simulation ticks."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import Counter

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
    event_type_counts: dict[str, int] = field(default_factory=dict)


class TelemetryRecorder:
    """Collects deterministic telemetry for debugging and tests."""

    def __init__(self) -> None:
        self.tick_history: list[TickTelemetry] = []
        self._current_stage_order: list[str] = []
        self.last_flushed_events: list[SimulationEvent] = []
        self.observed_event_types: list[str] = []
        self.observed_event_counts: dict[str, int] = {}
        self._observed_event_ids: set[str] = set()

    def record_stage(self, stage_name: str) -> None:
        """Record that a stage executed during the current tick."""

        self._current_stage_order.append(stage_name)

    def observe_event(self, event: SimulationEvent) -> None:
        """Observe emitted events through the in-process event bus exactly once per tick."""

        if event.event_id is not None and event.event_id in self._observed_event_ids:
            return
        self.observed_event_types.append(event.type.value)
        self.observed_event_counts[event.type.value] = self.observed_event_counts.get(event.type.value, 0) + 1
        if event.event_id is not None:
            self._observed_event_ids.add(event.event_id)

    def flush_tick(self, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
        """Emit a telemetry event and persist the per-tick telemetry summary."""

        events = event_bus.drain()
        event_types = [event.type.value for event in events]
        event_type_counts = (
            dict(self.observed_event_counts)
            if self.observed_event_counts
            else dict(Counter(event_types))
        )
        self.tick_history.append(
            TickTelemetry(
                tick=tick.tick,
                stage_order=list(self._current_stage_order),
                event_count=len(events),
                event_types=event_types,
                event_type_counts=event_type_counts,
            )
        )
        self._current_stage_order.clear()
        telemetry_event = SimulationEvent(
            type=EventType.TELEMETRY,
            tick=tick.tick,
            sim_time=tick.at,
            source_module="telemetry",
            payload={"event_count": len(events)},
        )
        self.last_flushed_events = [*events, telemetry_event]
        self._observed_event_ids.clear()
        self.observed_event_types = []
        self.observed_event_counts = {}
        return self.last_flushed_events
