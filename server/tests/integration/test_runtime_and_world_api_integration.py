"""Phase 3 integration tests for backend runtime orchestration and FastAPI endpoints."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import timedelta
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event as sqlalchemy_event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.models import WorldEvent
from app.engine.scheduler import ScheduledTask
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import AgentState, ResourceNodeState, TerrainType, TileState, WorldState, build_initial_world_state
from app.schemas.agent import AgentStateSnapshot
from app.schemas.event import EventType, SimulationEvent
from app.schemas.api import (
    AgentInspectResponse,
    BeliefsResponse,
    EpisodesResponse,
    ForceReflectResponse,
    GoalsResponse,
    RelationshipsResponse,
    ReplayResponse,
    TimelineResponse,
)


def test_runtime_step_once_updates_authoritative_state_end_to_end() -> None:
    """A world tick should advance time and update authoritative world state end to end."""

    async def run_test() -> None:
        runtime = _build_runtime()

        before = await runtime.get_snapshot()
        after = await runtime.step_once()

        assert after.tick == before.tick + 1
        assert after.generated_at >= before.generated_at
        assert after.world.width == before.world.width
        assert after.world.height == before.world.height
        assert after.agents[0].needs.hunger > before.agents[0].needs.hunger
        assert runtime._world_state.weather != "clear" or runtime._world_state.resource_level != 100.0

    asyncio.run(run_test())


def test_scheduler_dispatch_and_telemetry_integrate_with_world_tick() -> None:
    """Scheduler callbacks, runtime stepping, and telemetry should integrate in one tick."""

    async def run_test() -> None:
        runtime = _build_runtime()
        scheduled_events: list[tuple[str, int]] = []
        due_at = runtime._world_state.current_time + timedelta(seconds=60)

        def callback(now, event_bus) -> None:
            scheduled_events.append(("fired", runtime._world_state.tick))
            event_bus.emit(
                SimulationEvent(
                    type=EventType.MAJOR_LIFE_EVENT,
                    tick=runtime._world_state.tick,
                    sim_time=now,
                    agent_id=runtime._world_state.agents[0].agent_id,
                    payload={"source": "scheduler"},
                )
            )

        runtime._scheduler.schedule(
            ScheduledTask(
                due_at=due_at,
                callback=callback,
                task_id="phase3-major-life-event",
            )
        )

        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert scheduled_events == [("fired", 1)]
        assert debug_state["pending_scheduler_tasks"] == []
        assert debug_state["last_slow_loop_results"][0]["trigger_reasons"] == ["major_life_event"]
        assert debug_state["last_tick_telemetry"]["stage_order"] == [
            "clock.advance",
            "world.update_weather",
            "world.update_resources",
            "world.update_crops",
            "scheduler.dispatch_due_tasks",
            "agent_runtime.step_all",
        ]
        assert "major_life_event" in debug_state["last_tick_telemetry"]["event_types"]
        assert "action_executed" in debug_state["last_tick_telemetry"]["event_types"]

    asyncio.run(run_test())


def test_runtime_external_event_is_consumed_by_slow_loop_on_next_tick() -> None:
    """Externally emitted authoritative events should trigger the slow loop on the next tick."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.MAJOR_LIFE_EVENT,
            agent_id=runtime._world_state.agents[0].agent_id,
            payload={"kind": "integration-test"},
        )
        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert debug_state["tick"] == 1
        assert debug_state["last_slow_loop_results"][0]["trigger_reasons"] == ["major_life_event"]
        assert debug_state["last_slow_loop_results"][0]["applied"] is True
        assert debug_state["last_fast_loop_traces"][0]["stage_order"] == [
            "perceive",
            "update_needs",
            "score_actions",
            "plan",
            "execute",
            "emit_events",
        ]

    asyncio.run(run_test())


def test_runtime_agent_detail_services_return_typed_snapshots() -> None:
    """The runtime service should return rich typed agent snapshot DTOs, not raw dicts."""

    async def run_test() -> None:
        runtime = _build_runtime()

        collection = await runtime.get_agent_snapshots()
        single = await runtime.get_agent_snapshot("agent-1")

        assert collection
        assert all(isinstance(snapshot, AgentStateSnapshot) for snapshot in collection)
        assert isinstance(single, AgentStateSnapshot)
        assert single.agent_id == "agent-1"
        assert single.stage_of_life == "adult"

    asyncio.run(run_test())


def test_runtime_auxiliary_services_return_typed_endpoint_contracts() -> None:
    """The runtime should expose typed response models for the newer endpoint groups."""

    async def run_test() -> None:
        runtime = _build_runtime()

        reflection = await runtime.force_reflect("agent-1")
        relationships = await runtime.get_agent_relationships("agent-1")
        goals = await runtime.get_agent_goals("agent-1")
        timeline = await runtime.get_agent_timeline("agent-1")
        episodes = await runtime.get_memory_episodes("agent-1")
        beliefs = await runtime.get_memory_beliefs("agent-1")
        replay = await runtime.get_replay_events()
        inspect_agent = await runtime.inspect_agent("agent-1")

        assert isinstance(reflection, ForceReflectResponse)
        assert isinstance(relationships, RelationshipsResponse)
        assert isinstance(goals, GoalsResponse)
        assert isinstance(timeline, TimelineResponse)
        assert isinstance(episodes, EpisodesResponse)
        assert isinstance(beliefs, BeliefsResponse)
        assert isinstance(replay, ReplayResponse)
        assert isinstance(inspect_agent, AgentInspectResponse)
        assert reflection.agent_id == "agent-1"
        assert inspect_agent.agent.agent_id == "agent-1"

    asyncio.run(run_test())


def test_runtime_spawn_food_creates_authoritative_item_stack() -> None:
    """Admin food spawning should populate authoritative world items for the engine modules."""

    async def run_test() -> None:
        runtime = _build_runtime()

        response = await runtime.spawn_food(tile_x=2, tile_y=2, quantity=3, item_type="berries")

        assert response.item_type == "berries"
        assert response.quantity == 3
        assert len(runtime._world_state.items) == 1
        assert runtime._world_state.items[0].item_type == "berries"
        assert runtime._world_state.items[0].quantity == 3

    asyncio.run(run_test())


def test_runtime_resource_targeting_moves_agent_toward_water_and_finishes_resource_drink_plan() -> None:
    """Perception, planning, and execution should form a targeted water-seeking loop."""

    async def run_test() -> None:
        world = WorldState(
            width=4,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
            agents=[AgentState(agent_id="agent-1", name="A", x=0, y=1, thirst=80.0)],
            resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=1)],
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        first = await runtime.step_once()
        second = await runtime.step_once()
        third = await runtime.step_once()
        fourth = await runtime.step_once()
        debug_state = await runtime.get_debug_state()
        recent_events = await runtime.get_recent_world_events(limit=20)

        assert first.agents[0].position.x == 1
        assert second.agents[0].position.x == 2
        assert third.agents[0].needs.thirst < second.agents[0].needs.thirst
        assert fourth.agents[0].needs.thirst < third.agents[0].needs.thirst
        assert runtime._world_state.resources == []
        assert debug_state["last_fast_loop_traces"][0]["selected_action"] == "drink"
        assert any(event.event_type == "task_progress" for event in recent_events)
        assert any(event.event_type == "task_completed" for event in recent_events)

    asyncio.run(run_test())


def test_runtime_debug_state_surfaces_perception_planning_execution_and_lifecycle_signals() -> None:
    """The runtime debug surface should expose the wired engine-module flow for one tick."""

    async def run_test() -> None:
        world = WorldState(
            width=4,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
            agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1, thirst=70.0, health=0.0)],
            resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=1)],
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        trace = debug_state["last_fast_loop_traces"][0]
        assert trace["perception_summary"]["nearby_water"] is True
        assert trace["top_action_candidates"][0]["action"] == "drink"
        assert trace["planned_tasks"] == ["move_to", "fetch_water", "drink"]
        assert "action_executed" in trace["emitted_event_types"]
        assert "action_executed" in debug_state["last_fast_loop_event_types"]
        assert "death" in debug_state["last_lifecycle_event_types"]
        assert "death" in debug_state["last_tick_telemetry"]["event_types"]

    asyncio.run(run_test())


def test_runtime_recent_world_events_expose_shared_transport_shape_for_engine_events() -> None:
    """Recent runtime events should be adapted into stable world-event DTOs with actor ids and payloads."""

    async def run_test() -> None:
        world = WorldState(
            width=4,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
            agents=[AgentState(agent_id="agent-1", name="A", x=0, y=1, thirst=80.0)],
            resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=1)],
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        await runtime.step_once()
        recent_events = await runtime.get_recent_world_events(limit=10)

        assert recent_events
        assert all(event.event_id for event in recent_events)
        assert all(event.tick >= 1 for event in recent_events)
        assert any(event.event_type == "task_progress" for event in recent_events)
        assert any(event.event_type == "action_executed" for event in recent_events)

        action_event = next(event for event in recent_events if event.event_type == "action_executed")
        assert action_event.actor_ids == ["agent-1"]
        assert action_event.target_ids == []
        assert "action" in action_event.payload
        assert "position" in action_event.payload

    asyncio.run(run_test())


def test_runtime_event_bus_applies_relationship_listener_and_replay_projection() -> None:
    """Runtime-emitted social events should update authoritative state and reach replay/world-event surfaces."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.PROPOSAL_ACCEPTED,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"ring": "woven_grass"},
            source_module="integration-test",
        )

        assert runtime._world_state.agents[0].partner_id == "agent-2"
        assert runtime._world_state.agents[1].partner_id == "agent-1"

        await runtime.step_once()
        replay = await runtime.get_replay_events(limit=10)
        recent_events = await runtime.get_recent_world_events(limit=10)

        proposal_event = next(event for event in recent_events if event.event_type == "proposal_accepted")
        replay_event = next(event for event in replay.events if event.event_type == "proposal_accepted")

        assert proposal_event.actor_ids == ["agent-1"]
        assert proposal_event.target_ids == ["agent-2"]
        assert proposal_event.source_module == "integration-test"
        assert proposal_event.payload == {"ring": "woven_grass"}
        assert replay_event.agent_id == "agent-1"
        assert replay_event.payload == {"ring": "woven_grass"}

    asyncio.run(run_test())


def test_runtime_event_bus_projects_memories_and_telemetry_aggregates() -> None:
    """Important runtime events should update memories immediately and roll into telemetry aggregates."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"item_type": "berries"},
            source_module="integration-test",
        )

        assert "A gift changed hands." in runtime._world_state.agents[0].memories
        assert "A gift changed hands." in runtime._world_state.agents[1].memories

        await runtime.step_once()
        metrics = await runtime.get_debug_metrics()

        assert metrics.last_tick_event_type_counts["gift_given"] == 1
        assert "gift_given" in metrics.last_tick_event_types

    asyncio.run(run_test())


def test_runtime_event_bus_fans_out_consumption_events_across_memory_replay_and_telemetry() -> None:
    """Consumption events should update memories immediately and remain visible in replay and telemetry."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.AGENT_ATE,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"action": "eat"},
            source_module="integration-test",
        )
        await runtime.emit_simulation_event(
            EventType.AGENT_DRANK,
            agent_id="agent-2",
            actor_ids=["agent-2"],
            payload={"action": "drink"},
            source_module="integration-test",
        )

        assert "Ate a meal." in runtime._world_state.agents[0].memories
        assert "Drank fresh water." in runtime._world_state.agents[1].memories

        await runtime.step_once()
        replay = await runtime.get_replay_events(limit=20)
        metrics = await runtime.get_debug_metrics()
        recent_events = await runtime.get_recent_world_events(limit=20)

        assert {"agent_ate", "agent_drank"} <= {event.event_type for event in replay.events}
        assert metrics.last_tick_event_type_counts["agent_ate"] == 1
        assert metrics.last_tick_event_type_counts["agent_drank"] == 1
        assert {"agent_ate", "agent_drank"} <= {event.event_type for event in recent_events}

    asyncio.run(run_test())


def test_runtime_event_bus_fans_out_lifecycle_domain_events_with_optional_persistence() -> None:
    """Lifecycle-style events should reach memory, telemetry, replay, and persistence listeners together."""

    async def run_test() -> None:
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
        child_uuid = uuid.uuid4()
        runtime = SimulationRuntime(
            initial_state=build_initial_world_state(width=8, height=6, initial_agent_count=2),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: {
                "agent-1": actor_uuid,
                "agent-2": child_uuid,
            }.get(agent_id),
        )

        await runtime.emit_simulation_event(
            EventType.CHILD_BORN,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"child_id": "agent-2"},
            source_module="integration-test",
        )
        await runtime.emit_simulation_event(
            EventType.AGENT_DIED,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"kind": "health_failure"},
            source_module="integration-test",
        )

        assert "A child was born." in runtime._world_state.agents[0].memories
        assert "Death changed the village." in runtime._world_state.agents[0].memories

        await runtime.step_once()
        replay = await runtime.get_replay_events(limit=20)
        metrics = await runtime.get_debug_metrics()

        with session_scope() as session:
            persisted = session.scalars(select(WorldEvent).order_by(WorldEvent.tick, WorldEvent.id)).all()

        assert {"child_born", "agent_died"} <= {event.event_type for event in replay.events}
        assert metrics.last_tick_event_type_counts["child_born"] == 1
        assert metrics.last_tick_event_type_counts["agent_died"] == 1
        assert {"child_born", "agent_died"} <= {event.event_type for event in persisted}
        engine.dispose()

    asyncio.run(run_test())


def test_runtime_optional_world_event_persistence_listener_writes_to_repository() -> None:
    """Runtime should support an optional persistence listener without changing core loop ownership."""

    async def run_test() -> None:
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
        runtime = SimulationRuntime(
            initial_state=build_initial_world_state(width=8, height=6, initial_agent_count=2),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: {
                "agent-1": actor_uuid,
                "agent-2": target_uuid,
            }.get(agent_id),
        )

        await runtime.emit_simulation_event(
            EventType.PROPOSAL_ACCEPTED,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"ring": "woven_grass"},
            source_module="integration-test",
        )

        with session_scope() as session:
            persisted = session.scalars(select(WorldEvent)).all()

        assert len(persisted) == 1
        assert persisted[0].event_type == "proposal_accepted"
        assert persisted[0].actor_ids == [actor_uuid]
        assert persisted[0].target_ids == [target_uuid]
        assert persisted[0].payload == {"ring": "woven_grass"}

        engine.dispose()

    asyncio.run(run_test())


def test_tick_and_run_endpoints_advance_authoritative_state_end_to_end(client: TestClient) -> None:
    """The FastAPI tick and run endpoints should mutate authoritative backend state."""

    initial_snapshot = client.get("/api/v1/world/snapshot").json()
    tick_snapshot = client.post("/api/v1/world/tick").json()
    run_snapshot = client.post("/api/v1/world/run", json={"ticks": 2}).json()
    final_state = client.get("/api/v1/world/state").json()

    assert tick_snapshot["tick"] == initial_snapshot["tick"] + 1
    assert run_snapshot["tick"] == tick_snapshot["tick"] + 2
    assert final_state["tick"] == run_snapshot["tick"]
    assert final_state["agents"][0]["needs"]["hunger"] > initial_snapshot["agents"][0]["needs"]["hunger"]
    assert final_state["agents"][0]["current_action"] == run_snapshot["agents"][0]["current_action"]


def test_snapshot_and_state_endpoints_reflect_same_authoritative_backend_state(
    client: TestClient,
) -> None:
    """State and snapshot endpoints should agree after authoritative backend changes."""

    client.post("/api/v1/world/tick")
    client.post("/api/v1/world/tick")

    snapshot = client.get("/api/v1/world/snapshot").json()
    state = client.get("/api/v1/world/state").json()

    assert snapshot["tick"] == 2
    assert state["tick"] == 2
    assert snapshot["world"] == state["world"]
    assert snapshot["agents"] == state["agents"]


def test_agent_detail_endpoints_return_richer_typed_snapshot_contracts(client: TestClient) -> None:
    """Agent detail endpoints should expose the richer backend-facing snapshot DTOs."""

    collection = client.get("/api/v1/world/agents")
    single = client.get("/api/v1/world/agents/agent-1")

    assert collection.status_code == 200
    assert single.status_code == 200

    collection_payload = collection.json()
    single_payload = single.json()

    assert len(collection_payload["agents"]) >= 1
    assert single_payload["agent_id"] == "agent-1"
    assert single_payload["stage_of_life"] == "adult"
    assert single_payload["tile_x"] >= 0
    assert single_payload["tile_y"] >= 0
    assert set(single_payload["needs"].keys()) == {
        "hunger",
        "thirst",
        "fatigue",
        "warmth",
        "health",
        "stress",
        "loneliness",
        "safety",
    }
    assert set(single_payload["mood"].keys()) == {"hope", "grief", "morale", "shame"}


def test_agent_detail_endpoint_returns_404_for_unknown_agent(client: TestClient) -> None:
    """Unknown agents should fail cleanly on the richer detail endpoint."""

    response = client.get("/api/v1/world/agents/unknown-agent")

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Unknown agent 'unknown-agent'.",
    }


def _build_runtime() -> SimulationRuntime:
    """Build a real simulation runtime with deterministic initial state."""

    initial_world: WorldState = build_initial_world_state(width=8, height=6, initial_agent_count=2)
    return SimulationRuntime(initial_state=initial_world, tick_interval_seconds=60.0)
