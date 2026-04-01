"""Phase 3 integration tests for backend runtime orchestration and FastAPI endpoints."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi.testclient import TestClient

from app.engine.scheduler import ScheduledTask
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import WorldState, build_initial_world_state
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
