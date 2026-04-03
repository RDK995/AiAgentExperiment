"""Focused tests for authoritative event listeners and their thin integrations."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

from sqlalchemy import create_engine, event as sqlalchemy_event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.enums import AgentSex, StageOfLife
from app.db.base import Base, import_models
from app.db.models import WorldEvent
from app.engine.event_bus import EventBus
from app.engine.event_listeners import (
    MemoryEventListener,
    RelationshipEventListener,
    ReplayEventLog,
    WorldEventPersistenceListener,
)
from app.engine.world_state import AgentState, TerrainType, TileState, WorldState
from app.memory.writer import MemoryWriter
from app.schemas.event import EventType, SimulationEvent
from app.telemetry.metrics import TelemetryRecorder


def _world() -> WorldState:
    """Build a compact deterministic world for listener tests."""

    return WorldState(
        width=2,
        height=2,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(2) for x in range(2)],
        agents=[
            AgentState(agent_id="agent-1", name="A", x=0, y=0, sex=AgentSex.FEMALE, stage_of_life=StageOfLife.ADULT),
            AgentState(agent_id="agent-2", name="B", x=1, y=0, sex=AgentSex.MALE, stage_of_life=StageOfLife.ADULT),
        ],
    )


def _event(event_type: EventType, *, actor_ids: list[str], target_ids: list[str] | None = None) -> SimulationEvent:
    """Create a deterministic event with explicit actors and optional targets."""

    return SimulationEvent(
        type=event_type,
        tick=1,
        sim_time=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        actor_ids=actor_ids,
        target_ids=list(target_ids or []),
        payload={},
    )


def test_memory_listener_projects_important_events_into_agent_memories() -> None:
    """Important events should become compact memories for actor and target agents."""

    world = _world()
    listener = MemoryEventListener(lambda: world, MemoryWriter())
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(_event(EventType.GIFT_GIVEN, actor_ids=["agent-1"], target_ids=["agent-2"]))

    assert "A gift changed hands." in world.agents[0].memories
    assert "A gift changed hands." in world.agents[1].memories


def test_memory_listener_deduplicates_re_emitted_event_ids() -> None:
    """Memory projection should not write duplicate memories for the same emitted event id."""

    world = _world()
    listener = MemoryEventListener(lambda: world, MemoryWriter())
    bus = EventBus()
    bus.subscribe_all(listener.handle)
    event = _event(EventType.GIFT_GIVEN, actor_ids=["agent-1"], target_ids=["agent-2"])
    event.event_id = "evt-manual"

    bus.emit(event)
    bus.emit(event)

    assert world.agents[0].memories == ["A gift changed hands."]
    assert world.agents[1].memories == ["A gift changed hands."]


def test_relationship_listener_applies_proposal_acceptance_to_authoritative_state() -> None:
    """Proposal acceptance should update partner linkage on the authoritative agents."""

    world = _world()
    listener = RelationshipEventListener(lambda: world)
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(_event(EventType.PROPOSAL_ACCEPTED, actor_ids=["agent-1"], target_ids=["agent-2"]))

    assert world.agents[0].partner_id == "agent-2"
    assert world.agents[1].partner_id == "agent-1"


def test_relationship_listener_applies_social_side_effects_from_gifts_and_insults() -> None:
    """Social events should update authoritative social state through the shared listener."""

    world = _world()
    listener = RelationshipEventListener(lambda: world)
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(_event(EventType.GIFT_GIVEN, actor_ids=["agent-1"], target_ids=["agent-2"]))
    bus.emit(_event(EventType.INSULT_SPOKEN, actor_ids=["agent-1"], target_ids=["agent-2"]))

    assert world.agents[0].loneliness == 0.0
    assert world.agents[0].morale == 51.0
    assert world.agents[1].loneliness == 0.0
    assert world.agents[1].morale == 50.0
    assert world.agents[1].stress == 3.0
    assert world.agents[1].shame == 1.0


def test_relationship_listener_tracks_proposal_and_pregnancy_side_effects() -> None:
    """Proposal and pregnancy events should update the authoritative actor state deterministically."""

    world = _world()
    world.agents[0].hope = 40.0
    world.agents[1].hope = 35.0
    listener = RelationshipEventListener(lambda: world)
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(_event(EventType.PROPOSAL_MADE, actor_ids=["agent-1"], target_ids=["agent-2"]))
    bus.emit(_event(EventType.PREGNANCY_STARTED, actor_ids=["agent-1"], target_ids=["agent-2"]))

    assert world.agents[0].hope == 42.0
    assert world.agents[1].hope == 36.0
    assert world.agents[0].pregnancy_partner_id == "agent-2"


def test_replay_event_log_deduplicates_re_emitted_events() -> None:
    """Replay logging should not double-record the same event object when it is re-emitted."""

    replay_log = ReplayEventLog(max_events=10)
    bus = EventBus()
    bus.subscribe_all(replay_log.handle)
    event = _event(EventType.AGENT_ATE, actor_ids=["agent-1"])

    bus.emit(event)
    bus.emit(event)

    recorded = replay_log.recent_events(limit=10)
    assert len(recorded) == 1
    assert recorded[0].type is EventType.AGENT_ATE


def test_replay_event_log_projects_events_into_world_event_transport_shape() -> None:
    """Replay logging should expose authoritative events through the shared world-event DTO shape."""

    replay_log = ReplayEventLog(max_events=10)
    bus = EventBus()
    bus.subscribe_all(replay_log.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.PROPOSAL_ACCEPTED,
            tick=3,
            sim_time=datetime(2000, 1, 1, 8, 3, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=4,
            location_y=5,
            source_module="social",
            payload={"ring": "woven_grass"},
        )
    )

    projected = replay_log.recent_world_events(limit=10)

    assert len(projected) == 1
    assert projected[0].event_type == "proposal_accepted"
    assert projected[0].actor_ids == ["agent-1"]
    assert projected[0].target_ids == ["agent-2"]
    assert projected[0].location_x == 4
    assert projected[0].location_y == 5
    assert projected[0].source_module == "social"
    assert projected[0].payload == {"ring": "woven_grass"}


def test_replay_event_log_bounds_seen_ids_with_trimmed_history() -> None:
    """Replay dedupe ids should stay aligned with the bounded replay window."""

    replay_log = ReplayEventLog(max_events=2)

    replay_log.record(
        SimulationEvent(
            event_id="evt-1",
            type=EventType.AGENT_ATE,
            tick=1,
            sim_time=datetime(2000, 1, 1, 8, 1, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            payload={},
        )
    )
    replay_log.record(
        SimulationEvent(
            event_id="evt-2",
            type=EventType.AGENT_DRANK,
            tick=2,
            sim_time=datetime(2000, 1, 1, 8, 2, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            payload={},
        )
    )
    replay_log.record(
        SimulationEvent(
            event_id="evt-3",
            type=EventType.GIFT_GIVEN,
            tick=3,
            sim_time=datetime(2000, 1, 1, 8, 3, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={},
        )
    )

    assert [event.event_id for event in replay_log.recent_events(limit=10)] == ["evt-2", "evt-3"]
    assert replay_log._seen_event_ids == {"evt-2", "evt-3"}

    replay_log.record(
        SimulationEvent(
            event_id="evt-1",
            type=EventType.AGENT_ATE,
            tick=4,
            sim_time=datetime(2000, 1, 1, 8, 4, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            payload={"replayed": True},
        )
    )

    assert [event.event_id for event in replay_log.recent_events(limit=10)] == ["evt-3", "evt-1"]
    assert replay_log._seen_event_ids == {"evt-3", "evt-1"}


def test_telemetry_recorder_can_observe_events_as_a_bus_listener() -> None:
    """Telemetry should be able to observe emitted events without replacing the drain-based flow."""

    telemetry = TelemetryRecorder()
    bus = EventBus()
    bus.subscribe_all(telemetry.observe_event)

    bus.emit(_event(EventType.AGENT_ATE, actor_ids=["agent-1"]))
    bus.emit(_event(EventType.AGENT_DRANK, actor_ids=["agent-1"]))

    assert telemetry.observed_event_types == ["agent_ate", "agent_drank"]
    assert telemetry.observed_event_counts == {"agent_ate": 1, "agent_drank": 1}


def test_world_event_persistence_listener_persists_important_events() -> None:
    """Important bus events should be persistable through the existing world-event repository shape."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @sqlalchemy_event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def session_scope():
        session: Session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    actor_uuid = uuid.uuid4()
    target_uuid = uuid.uuid4()
    listener = WorldEventPersistenceListener(
        session_scope,
        resolve_agent_id=lambda agent_id: {
            "agent-1": actor_uuid,
            "agent-2": target_uuid,
        }.get(agent_id),
    )
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    bus.emit(
        SimulationEvent(
            type=EventType.GIFT_GIVEN,
            tick=5,
            sim_time=datetime(2000, 1, 1, 8, 5, tzinfo=timezone.utc),
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=1,
            location_y=0,
            source_module="social",
            payload={"item_type": "berries"},
        )
    )

    with session_scope() as session:
        persisted = session.scalars(select(WorldEvent)).all()

    assert len(persisted) == 1
    assert persisted[0].tick == 5
    assert persisted[0].event_type == "gift_given"
    assert persisted[0].actor_ids == [actor_uuid]
    assert persisted[0].target_ids == [target_uuid]
    assert persisted[0].location_x == 1
    assert persisted[0].location_y == 0
    assert persisted[0].payload == {"item_type": "berries"}

    engine.dispose()


def test_world_event_persistence_listener_skips_telemetry_and_deduplicates_event_ids() -> None:
    """Persistence listener should ignore telemetry noise and avoid double-writing the same event id."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @sqlalchemy_event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)

    @contextmanager
    def session_scope():
        session: Session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    listener = WorldEventPersistenceListener(session_scope)
    bus = EventBus()
    bus.subscribe_all(listener.handle)

    telemetry_event = SimulationEvent(
        event_id="evt-telemetry",
        type=EventType.TELEMETRY,
        tick=5,
        sim_time=datetime(2000, 1, 1, 8, 5, tzinfo=timezone.utc),
        payload={"event_count": 2},
    )
    important_event = SimulationEvent(
        event_id="evt-important",
        type=EventType.GIFT_GIVEN,
        tick=6,
        sim_time=datetime(2000, 1, 1, 8, 6, tzinfo=timezone.utc),
        actor_ids=["agent-1"],
        target_ids=["agent-2"],
        payload={"item_type": "berries"},
    )

    bus.emit(telemetry_event)
    bus.emit(important_event)
    bus.emit(important_event)

    with session_scope() as session:
        persisted = session.scalars(select(WorldEvent).order_by(WorldEvent.tick, WorldEvent.id)).all()

    assert len(persisted) == 1
    assert persisted[0].tick == 6
    assert persisted[0].event_type == "gift_given"

    engine.dispose()
