"""Thin in-process listeners for authoritative simulation events."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
import uuid

from sqlalchemy.orm import Session

from app.db.repositories.world import AgentIdResolver, WorldRepository
from app.engine.world_state import AgentState, WorldState
from app.memory.writer import MemoryWriter
from app.schemas.event import EventType, SimulationEvent, WorldEventSchema


class MemoryEventListener:
    """Project selected important events into compact agent memories."""

    def __init__(self, world_getter: Callable[[], WorldState], memory_writer: MemoryWriter) -> None:
        self._world_getter = world_getter
        self._memory_writer = memory_writer
        self._seen_event_ids: set[str] = set()

    def handle(self, event: SimulationEvent) -> None:
        """Write a compact memory summary for important actor/target events."""

        if event.event_id is not None and event.event_id in self._seen_event_ids:
            return

        summary = _memory_summary(event)
        if summary is None:
            if event.event_id is not None:
                self._seen_event_ids.add(event.event_id)
            return

        world = self._world_getter()
        affected_ids = list(dict.fromkeys([*event.actor_ids, *event.target_ids]))
        for agent_id in affected_ids:
            agent = world.agent_by_id(agent_id)
            if agent is not None:
                self._memory_writer.write(agent, [summary])

        if event.event_id is not None:
            self._seen_event_ids.add(event.event_id)


class RelationshipEventListener:
    """Apply lightweight relationship side effects from social/family events."""

    def __init__(self, world_getter: Callable[[], WorldState]) -> None:
        self._world_getter = world_getter
        self._seen_event_ids: set[str] = set()

    def handle(self, event: SimulationEvent) -> None:
        """Apply deterministic relationship mutations for supported events."""

        if event.event_id is not None and event.event_id in self._seen_event_ids:
            return

        world = self._world_getter()
        if event.type is EventType.GIFT_GIVEN and event.actor_ids and event.target_ids:
            actor = world.agent_by_id(event.actor_ids[0])
            target = world.agent_by_id(event.target_ids[0])
            if actor is not None:
                actor.loneliness = max(0.0, actor.loneliness - 1.0)
                actor.morale = min(100.0, actor.morale + 1.0)
            if target is not None:
                target.loneliness = max(0.0, target.loneliness - 2.0)
                target.morale = min(100.0, target.morale + 2.0)
        if event.type is EventType.INSULT_SPOKEN and event.target_ids:
            target = world.agent_by_id(event.target_ids[0])
            if target is not None:
                target.stress = min(100.0, target.stress + 3.0)
                target.shame = min(100.0, target.shame + 1.0)
                target.morale = max(0.0, target.morale - 2.0)
        if event.type is EventType.PROPOSAL_MADE and event.actor_ids:
            actor = world.agent_by_id(event.actor_ids[0])
            if actor is not None:
                actor.hope = min(100.0, actor.hope + 2.0)
            if event.target_ids:
                target = world.agent_by_id(event.target_ids[0])
                if target is not None:
                    target.hope = min(100.0, target.hope + 1.0)
        if event.type is EventType.PROPOSAL_ACCEPTED and event.actor_ids and event.target_ids:
            actor = world.agent_by_id(event.actor_ids[0])
            target = world.agent_by_id(event.target_ids[0])
            if actor is not None and target is not None:
                actor.partner_id = target.agent_id
                target.partner_id = actor.agent_id
                actor.hope = min(100.0, actor.hope + 3.0)
                target.hope = min(100.0, target.hope + 3.0)
                actor.morale = min(100.0, actor.morale + 2.0)
                target.morale = min(100.0, target.morale + 2.0)
        if event.type is EventType.PREGNANCY_STARTED and event.actor_ids and event.target_ids:
            actor = world.agent_by_id(event.actor_ids[0])
            if actor is not None:
                actor.pregnancy_partner_id = event.target_ids[0]

        if event.event_id is not None:
            self._seen_event_ids.add(event.event_id)


class ReplayEventLog:
    """Store a bounded authoritative event history for replay/debugging."""

    def __init__(self, max_events: int = 200) -> None:
        self._max_events = max_events
        self._events: list[SimulationEvent] = []
        self._seen_event_ids: set[str] = set()

    def handle(self, event: SimulationEvent) -> None:
        """Record an event exactly once, even if the same object is re-emitted."""

        self.record(event)

    def record(self, event: SimulationEvent) -> None:
        """Record an event outside the live bus dispatch path."""

        if event.event_id is not None and event.event_id in self._seen_event_ids:
            return
        self._events.append(event)
        self._events = self._events[-self._max_events :]
        if event.event_id is not None:
            self._seen_event_ids.add(event.event_id)

    def recent_events(self, limit: int = 200) -> list[SimulationEvent]:
        """Return a bounded copy of the replayable event log."""

        return list(self._events[-limit:])

    def recent_world_events(self, limit: int = 200) -> list[WorldEventSchema]:
        """Return replayed events using the shared world-event transport contract."""

        recent = self.recent_events(limit=limit)
        start_index = max(0, len(self._events) - len(recent))
        return [
            WorldEventSchema.from_simulation_event(
                event,
                fallback_event_id=f"{event.tick}-{start_index + index}-{event.type.value}",
            )
            for index, event in enumerate(recent)
        ]


class WorldEventPersistenceListener:
    """Persist selected authoritative events into the existing world-event repository."""

    def __init__(
        self,
        session_scope: Callable[[], AbstractContextManager[Session]],
        *,
        resolve_agent_id: AgentIdResolver | None = None,
        should_persist: Callable[[SimulationEvent], bool] | None = None,
    ) -> None:
        self._session_scope = session_scope
        self._resolve_agent_id = resolve_agent_id
        self._should_persist = should_persist or _should_persist_event
        self._seen_event_ids: set[str] = set()

    def handle(self, event: SimulationEvent) -> None:
        """Persist one authoritative event exactly once when it matches the persistence policy."""

        if event.event_id is not None and event.event_id in self._seen_event_ids:
            return
        if not self._should_persist(event):
            if event.event_id is not None:
                self._seen_event_ids.add(event.event_id)
            return

        with self._session_scope() as session:
            repository = WorldRepository(session)
            params = repository.world_event_params_from_simulation_event(
                event,
                resolve_agent_id=self._resolve_agent_id,
            )
            repository.create_world_event(params)

        if event.event_id is not None:
            self._seen_event_ids.add(event.event_id)


def _memory_summary(event: SimulationEvent) -> str | None:
    """Build a compact memory summary for selected important events."""

    summaries = {
        EventType.AGENT_ATE: "Ate a meal.",
        EventType.AGENT_DRANK: "Drank fresh water.",
        EventType.GIFT_GIVEN: "A gift changed hands.",
        EventType.INSULT_SPOKEN: "A harsh insult was spoken.",
        EventType.PROPOSAL_MADE: "A proposal was made.",
        EventType.PROPOSAL_ACCEPTED: "A proposal was accepted.",
        EventType.PREGNANCY_STARTED: "Pregnancy began.",
        EventType.CHILD_BORN: "A child was born.",
        EventType.AGENT_DIED: "Death changed the village.",
        EventType.FOOD_STORE_EMPTY: "A food source ran dry.",
        EventType.CROP_FAILED: "Crops failed.",
    }
    return summaries.get(event.type)


def _should_persist_event(event: SimulationEvent) -> bool:
    """Persist important authoritative events while skipping telemetry noise."""

    return event.type is not EventType.TELEMETRY


def actor_at(world: WorldState, actor_id: str) -> AgentState | None:
    """Convenience helper for tests and listener integrations."""

    return world.agent_by_id(actor_id)
