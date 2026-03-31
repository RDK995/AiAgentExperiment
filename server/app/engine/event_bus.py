"""Simple in-memory event bus for the prototype simulation."""

from __future__ import annotations

from collections import deque

from app.schemas.event import SimulationEvent


class EventBus:
    """Queues simulation events emitted during authoritative ticks."""

    def __init__(self) -> None:
        self._events: deque[SimulationEvent] = deque()

    def emit(self, event: SimulationEvent) -> None:
        """Record an event for downstream processing."""

        self._events.append(event)

    def drain(self) -> list[SimulationEvent]:
        """Return and clear queued events."""

        events = list(self._events)
        self._events.clear()
        return events
