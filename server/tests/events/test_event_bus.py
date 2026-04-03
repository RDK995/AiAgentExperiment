"""Focused tests for the authoritative in-process event bus."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.engine.event_bus import EventBus
from app.schemas.event import EventType, SimulationEvent


def _event(event_type: EventType, *, agent_id: str | None = "agent-1") -> SimulationEvent:
    """Build a deterministic simulation event for event-bus tests."""

    return SimulationEvent(
        type=event_type,
        tick=1,
        sim_time=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        agent_id=agent_id,
        payload={"kind": event_type.value},
    )


def test_specific_listeners_receive_only_matching_event_types() -> None:
    """Typed listeners should fire only for subscribed event types."""

    bus = EventBus()
    seen: list[str] = []
    bus.subscribe(EventType.AGENT_ATE, lambda event: seen.append(event.type.value))

    bus.emit(_event(EventType.AGENT_ATE))
    bus.emit(_event(EventType.AGENT_DRANK))

    assert seen == ["agent_ate"]


def test_publish_dispatches_in_deterministic_subscription_order() -> None:
    """Specific listeners should run before global listeners, preserving registration order."""

    bus = EventBus()
    call_order: list[str] = []
    bus.subscribe(EventType.AGENT_ATE, lambda event: call_order.append("typed-1"))
    bus.subscribe(EventType.AGENT_ATE, lambda event: call_order.append("typed-2"))
    bus.subscribe_all(lambda event: call_order.append("global-1"))
    bus.subscribe_all(lambda event: call_order.append("global-2"))

    bus.emit(_event(EventType.AGENT_ATE))

    assert call_order == ["typed-1", "typed-2", "global-1", "global-2"]


def test_multiple_listeners_receive_same_event_and_payload_is_preserved() -> None:
    """The same event instance should be delivered to all listeners with its structured payload intact."""

    bus = EventBus()
    payloads: list[tuple[list[str], list[str], int | None, int | None, str | None]] = []
    bus.subscribe_all(
        lambda event: payloads.append(
            (list(event.actor_ids), list(event.target_ids), event.location_x, event.location_y, event.source_module)
        )
    )
    event = SimulationEvent(
        type=EventType.GIFT_GIVEN,
        tick=2,
        sim_time=datetime(2000, 1, 1, 8, 5, tzinfo=timezone.utc),
        actor_ids=["agent-1"],
        target_ids=["agent-2"],
        location_x=3,
        location_y=4,
        source_module="social",
        payload={"item_type": "berries"},
    )

    bus.emit(event)

    assert event.event_id is not None
    assert payloads == [(["agent-1"], ["agent-2"], 3, 4, "social")]
    drained = bus.drain()
    assert drained[0].payload == {"item_type": "berries"}


def test_listener_failures_are_not_swallowed_and_event_remains_queued() -> None:
    """Listener errors should fail fast without silently losing the emitted event."""

    bus = EventBus()

    def fail(_: SimulationEvent) -> None:
        raise RuntimeError("boom")

    bus.subscribe(EventType.AGENT_ATE, fail)

    with pytest.raises(RuntimeError, match="boom"):
        bus.emit(_event(EventType.AGENT_ATE))

    drained = bus.drain()
    assert len(drained) == 1
    assert drained[0].type is EventType.AGENT_ATE


def test_emit_many_preserves_input_order() -> None:
    """Batch emission should dispatch and queue events in list order."""

    bus = EventBus()
    seen: list[str] = []
    bus.subscribe_all(lambda event: seen.append(event.type.value))

    bus.emit_many([_event(EventType.AGENT_ATE), _event(EventType.AGENT_DRANK)])

    assert seen == ["agent_ate", "agent_drank"]
    assert [event.type.value for event in bus.drain()] == ["agent_ate", "agent_drank"]


def test_event_bus_assigns_monotonic_event_ids_and_preserves_existing_ids() -> None:
    """Auto-assigned event ids should be deterministic and should not overwrite explicit ids."""

    bus = EventBus()
    first = _event(EventType.AGENT_ATE)
    second = _event(EventType.AGENT_DRANK)
    explicit = _event(EventType.GIFT_GIVEN)
    explicit.event_id = "external-42"

    bus.emit(first)
    bus.emit(second)
    bus.emit(explicit)

    drained = bus.drain()

    assert first.event_id == "evt-1"
    assert second.event_id == "evt-2"
    assert explicit.event_id == "external-42"
    assert [event.event_id for event in drained] == ["evt-1", "evt-2", "external-42"]


def test_listener_failure_stops_later_listeners_after_the_failure_point() -> None:
    """Fail-fast dispatch should stop subsequent listeners once a listener raises."""

    bus = EventBus()
    calls: list[str] = []

    def typed_first(_: SimulationEvent) -> None:
        calls.append("typed-first")

    def typed_fail(_: SimulationEvent) -> None:
        calls.append("typed-fail")
        raise RuntimeError("stop here")

    def typed_late(_: SimulationEvent) -> None:
        calls.append("typed-late")

    def global_late(_: SimulationEvent) -> None:
        calls.append("global-late")

    bus.subscribe(EventType.AGENT_ATE, typed_first)
    bus.subscribe(EventType.AGENT_ATE, typed_fail)
    bus.subscribe(EventType.AGENT_ATE, typed_late)
    bus.subscribe_all(global_late)

    with pytest.raises(RuntimeError, match="stop here"):
        bus.emit(_event(EventType.AGENT_ATE))

    assert calls == ["typed-first", "typed-fail"]
