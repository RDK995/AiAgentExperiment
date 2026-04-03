"""Simple in-memory event bus for the prototype simulation."""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable

from app.schemas.event import EventType, SimulationEvent

EventHandler = Callable[[SimulationEvent], None]


class EventBus:
    """Queues and dispatches authoritative simulation events.

    Dispatch is synchronous and deterministic:
    1. the event is assigned an id if needed
    2. the event is queued for downstream drain-based consumers
    3. typed listeners run in subscription order
    4. global listeners run in subscription order

    Listener failures are not swallowed. The bus fails fast so authoritative
    callers cannot silently lose an important event.
    """

    def __init__(self) -> None:
        self._events: deque[SimulationEvent] = deque()
        self._typed_listeners: dict[EventType, list[EventHandler]] = defaultdict(list)
        self._global_listeners: list[EventHandler] = []
        self._next_event_index = 1

    def subscribe(self, event_type: EventType, handler: EventHandler) -> None:
        """Register a listener for a single event type."""

        self._typed_listeners[event_type].append(handler)

    def subscribe_all(self, handler: EventHandler) -> None:
        """Register a listener for all emitted events."""

        self._global_listeners.append(handler)

    def emit(self, event: SimulationEvent) -> None:
        """Record and synchronously dispatch an event."""

        if event.event_id is None:
            event.event_id = f"evt-{self._next_event_index}"
            self._next_event_index += 1
        self._events.append(event)
        for handler in self._typed_listeners.get(event.type, []):
            handler(event)
        for handler in self._global_listeners:
            handler(event)

    def emit_many(self, events: list[SimulationEvent]) -> None:
        """Emit a deterministic batch of events in list order."""

        for event in events:
            self.emit(event)

    def drain(self) -> list[SimulationEvent]:
        """Return and clear queued events."""

        events = list(self._events)
        self._events.clear()
        return events
