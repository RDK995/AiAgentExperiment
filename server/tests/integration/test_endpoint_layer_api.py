"""Integration tests for the broader FastAPI endpoint layer."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.schemas.agent import AgentStateSnapshot
from app.schemas.api import (
    AdvanceDaysResponse,
    AgentListResponse,
    AgentInspectResponse,
    ChunkResponse,
    DailyMetricsDebugResponse,
    DebugMetricsResponse,
    EpisodesResponse,
    ForceReflectResponse,
    GoalsResponse,
    MemoryRetrieveResponse,
    MemorySummarizeResponse,
    RecentWorldEventsResponse,
    ReflectionRunsResponse,
    RelationshipsResponse,
    ResetWorldResponse,
    ReplayResponse,
    SeedResponse,
    SimulationSnapshot,
    SpawnAgentResponse,
    SpawnFoodResponse,
    TimelineResponse,
    WorldStreamEnvelope,
)


def test_app_registers_new_endpoint_groups(client: TestClient) -> None:
    """The app should expose the new world, agent, memory, debug, and admin routes."""

    route_paths = {route.path for route in client.app.routes}

    assert "/api/v1/world/state" in route_paths
    assert "/api/v1/world/chunk/{x}/{y}" in route_paths
    assert "/api/v1/world/events/recent" in route_paths
    assert "/api/v1/world/stream" in route_paths
    assert "/api/v1/world/tick/run" in route_paths
    assert "/api/v1/world/seed" in route_paths
    assert "/api/v1/agents" in route_paths
    assert "/api/v1/agents/{agent_id}" in route_paths
    assert "/api/v1/agents/{agent_id}/relationships" in route_paths
    assert "/api/v1/agents/{agent_id}/goals" in route_paths
    assert "/api/v1/agents/{agent_id}/timeline" in route_paths
    assert "/api/v1/agents/{agent_id}/step" in route_paths
    assert "/api/v1/agents/{agent_id}/force-reflect" in route_paths
    assert "/api/v1/memory/{agent_id}/episodes" in route_paths
    assert "/api/v1/memory/{agent_id}/beliefs" in route_paths
    assert "/api/v1/memory/{agent_id}/daily-summary-candidates" in route_paths
    assert "/api/v1/memory/{agent_id}/retrieve" in route_paths
    assert "/api/v1/memory/{agent_id}/summarize" in route_paths
    assert "/api/v1/debug/metrics" in route_paths
    assert "/api/v1/debug/metrics/daily" in route_paths
    assert "/api/v1/debug/replay" in route_paths
    assert "/api/v1/debug/reflections" in route_paths
    assert "/api/v1/debug/inspect/agent/{agent_id}" in route_paths
    assert "/api/v1/debug/inspect/household/{household_id}" in route_paths
    assert "/api/v1/admin/spawn-agent" in route_paths
    assert "/api/v1/admin/spawn-food" in route_paths
    assert "/api/v1/admin/advance-days/{days}" in route_paths
    assert "/api/v1/admin/reset-world" in route_paths


def test_world_state_and_tick_run_endpoints_work(client: TestClient) -> None:
    """World state and tick-run endpoints should return successful authoritative snapshots."""

    before = client.get("/api/v1/world/state")
    after = client.post("/api/v1/world/tick/run", json={"ticks": 2})

    assert before.status_code == 200
    assert after.status_code == 200
    assert after.json()["tick"] == before.json()["tick"] + 2
    assert isinstance(SimulationSnapshot.model_validate(before.json()), SimulationSnapshot)
    assert isinstance(SimulationSnapshot.model_validate(after.json()), SimulationSnapshot)


def test_world_chunk_and_recent_events_endpoints_return_typed_shapes(client: TestClient) -> None:
    """Chunk and recent-event endpoints should expose stable typed response contracts."""

    client.post("/api/v1/world/tick")

    chunk = client.get("/api/v1/world/chunk/0/0")
    events = client.get("/api/v1/world/events/recent")

    assert chunk.status_code == 200
    assert events.status_code == 200

    chunk_payload = chunk.json()
    events_payload = events.json()["events"]

    assert {"anchor_x", "anchor_y", "width", "height", "tiles", "agents"} == set(chunk_payload)
    assert isinstance(ChunkResponse.model_validate(chunk_payload), ChunkResponse)
    assert isinstance(events_payload, list)
    assert events_payload
    assert {"event_id", "tick", "event_type", "actor_ids", "target_ids", "payload"} <= set(events_payload[0])

    assert isinstance(RecentWorldEventsResponse.model_validate(events.json()), RecentWorldEventsResponse)


def test_world_stream_websocket_emits_seed_definition_and_snapshot_batch(client: TestClient) -> None:
    """The live world stream should expose seed bootstrap and typed snapshot/event batches."""

    with client.websocket_connect(
        "/api/v1/world/stream?seed_id=v1_village&seed_on_connect=true&poll_seconds=0.05"
    ) as websocket:
        seed_message = websocket.receive_json()
        batch_message = websocket.receive_json()

    seed_envelope = WorldStreamEnvelope.model_validate(seed_message)
    batch_envelope = WorldStreamEnvelope.model_validate(batch_message)

    assert seed_envelope.message_type == "seed_definition"
    assert seed_envelope.seed_definition is not None
    assert seed_envelope.seed_definition.seed_id == "v1_village"

    assert batch_envelope.message_type == "snapshot_batch"
    assert batch_envelope.snapshot_batch is not None
    assert batch_envelope.snapshot_batch.snapshot.world.width == 64
    assert len(batch_envelope.snapshot_batch.snapshot.agents) == 20


def test_world_stream_websocket_reflects_live_tick_updates(client: TestClient) -> None:
    """The live stream should advance with authoritative backend ticks."""

    with client.websocket_connect(
        "/api/v1/world/stream?seed_id=v1_village&seed_on_connect=true&poll_seconds=0.05"
    ) as websocket:
        websocket.receive_json()
        initial_batch = WorldStreamEnvelope.model_validate(websocket.receive_json())
        initial_tick = initial_batch.snapshot_batch.snapshot.tick

        client.post("/api/v1/world/tick")
        next_batch = WorldStreamEnvelope.model_validate(websocket.receive_json())

    assert next_batch.message_type == "snapshot_batch"
    assert next_batch.snapshot_batch is not None
    assert next_batch.snapshot_batch.snapshot.tick >= initial_tick + 1


def test_world_stream_does_not_reseed_backend_by_default(client: TestClient) -> None:
    """Connecting the presentation stream should not reset authoritative state unless explicitly requested."""

    client.post("/api/v1/world/tick")
    client.post("/api/v1/world/tick")
    before = client.get("/api/v1/world/snapshot").json()

    with client.websocket_connect("/api/v1/world/stream") as websocket:
        first_message = WorldStreamEnvelope.model_validate(websocket.receive_json())
        second_message = WorldStreamEnvelope.model_validate(websocket.receive_json())

    after = client.get("/api/v1/world/snapshot").json()

    assert first_message.message_type == "warning"
    assert first_message.warning == "No fixed world seed is active on the backend; streaming snapshot-only state."
    assert second_message.message_type == "snapshot_batch"
    assert second_message.snapshot_batch is not None
    assert second_message.snapshot_batch.snapshot.tick == before["tick"]
    assert before["tick"] == after["tick"]
    assert before["world"] == after["world"]
    assert before["agents"] == after["agents"]


def test_world_stream_emits_new_seed_definition_after_runtime_reseed(client: TestClient) -> None:
    """A connected client should receive an updated seed definition when the backend activates a fixed seed."""

    with client.websocket_connect("/api/v1/world/stream?poll_seconds=0.05") as websocket:
        warning_message = WorldStreamEnvelope.model_validate(websocket.receive_json())
        initial_batch = WorldStreamEnvelope.model_validate(websocket.receive_json())

        client.post("/api/v1/world/seed", json={"seed_id": "v1_village"})
        seed_message = WorldStreamEnvelope.model_validate(websocket.receive_json())
        next_batch = WorldStreamEnvelope.model_validate(websocket.receive_json())

    assert warning_message.message_type == "warning"
    assert initial_batch.message_type == "snapshot_batch"
    assert seed_message.message_type == "seed_definition"
    assert seed_message.seed_definition is not None
    assert seed_message.seed_definition.seed_id == "v1_village"
    assert next_batch.message_type == "snapshot_batch"
    assert next_batch.snapshot_batch is not None
    assert next_batch.snapshot_batch.snapshot.world.width == 64


def test_world_chunk_and_seed_invalid_inputs_fail_cleanly(client: TestClient) -> None:
    """World routes should reject invalid path and body inputs through the contract layer."""

    invalid_chunk = client.get("/api/v1/world/chunk/-1/0")
    out_of_bounds_chunk = client.get("/api/v1/world/chunk/16/0")
    invalid_seed = client.post("/api/v1/world/seed", json={"agent_count": 0})

    assert invalid_chunk.status_code == 400
    assert invalid_chunk.json() == {
        "error": "bad_request",
        "message": "Chunk coordinates must be non-negative.",
    }
    assert out_of_bounds_chunk.status_code == 400
    assert out_of_bounds_chunk.json() == {
        "error": "bad_request",
        "message": "Chunk coordinates must fall within world bounds.",
    }
    assert invalid_seed.status_code == 422
    assert invalid_seed.json()["detail"][0]["loc"] == ["body", "agent_count"]


def test_world_seed_endpoint_resets_to_baseline(client: TestClient) -> None:
    """World seed should reset the runtime and return a clean summary."""

    client.post("/api/v1/world/tick")
    response = client.post("/api/v1/world/seed")

    assert response.status_code == 200
    assert response.json()["status"] == "seeded"
    assert response.json()["tick"] == 0
    assert isinstance(SeedResponse.model_validate(response.json()), SeedResponse)


def test_world_seed_endpoint_accepts_optional_agent_count(client: TestClient) -> None:
    """World seed should accept the typed optional seed payload and apply it."""

    response = client.post("/api/v1/world/seed", json={"agent_count": 5})
    listing = client.get("/api/v1/agents")

    assert response.status_code == 200
    assert response.json()["seeded_agents"] == 5
    assert len(listing.json()["agents"]) == 5


def test_agents_routes_return_expected_shapes_and_errors(client: TestClient) -> None:
    """Agent endpoints should provide typed payloads and clean missing-agent failures."""

    listing = client.get("/api/v1/agents")
    detail = client.get("/api/v1/agents/agent-1")
    relationships = client.get("/api/v1/agents/agent-1/relationships")
    goals = client.get("/api/v1/agents/agent-1/goals")
    timeline = client.get("/api/v1/agents/agent-1/timeline")
    missing = client.get("/api/v1/agents/missing-agent")

    assert listing.status_code == 200
    assert detail.status_code == 200
    assert relationships.status_code == 200
    assert goals.status_code == 200
    assert timeline.status_code == 200
    assert missing.status_code == 404

    listing_payload = listing.json()
    detail_payload = detail.json()
    assert isinstance(listing_payload["agents"], list)
    assert isinstance(AgentListResponse.model_validate(listing_payload), AgentListResponse)
    assert isinstance(AgentStateSnapshot.model_validate(detail_payload), AgentStateSnapshot)
    assert detail_payload["agent_id"] == "agent-1"
    assert detail_payload["stage_of_life"] == "adult"
    assert set(detail_payload["mood"].keys()) == {"hope", "grief", "morale", "shame"}
    assert missing.json() == {
        "error": "not_found",
        "message": "Unknown agent 'missing-agent'.",
    }


def test_agent_summary_routes_conform_to_typed_wrapper_contracts(client: TestClient) -> None:
    """Relationship, goal, and timeline routes should return their typed wrapper payloads."""

    client.post("/api/v1/agents/agent-1/force-reflect")
    relationships = client.get("/api/v1/agents/agent-1/relationships")
    goals = client.get("/api/v1/agents/agent-1/goals")
    timeline = client.get("/api/v1/agents/agent-1/timeline")

    assert relationships.status_code == 200
    assert goals.status_code == 200
    assert timeline.status_code == 200

    assert isinstance(RelationshipsResponse.model_validate(relationships.json()), RelationshipsResponse)
    assert isinstance(GoalsResponse.model_validate(goals.json()), GoalsResponse)
    assert isinstance(TimelineResponse.model_validate(timeline.json()), TimelineResponse)


def test_agent_step_and_force_reflect_routes_work(client: TestClient) -> None:
    """Agent control routes should drive the authoritative runtime cleanly."""

    stepped = client.post("/api/v1/agents/agent-1/step")
    reflected = client.post("/api/v1/agents/agent-1/force-reflect")

    assert stepped.status_code == 200
    assert reflected.status_code == 200
    assert stepped.json()["agent_id"] == "agent-1"
    assert reflected.json()["agent_id"] == "agent-1"
    assert "trigger_reasons" in reflected.json()
    assert isinstance(AgentStateSnapshot.model_validate(stepped.json()), AgentStateSnapshot)
    assert isinstance(ForceReflectResponse.model_validate(reflected.json()), ForceReflectResponse)


def test_agent_control_routes_return_clean_not_found_for_missing_agent(client: TestClient) -> None:
    """Agent control routes should return standardized not-found payloads for missing agents."""

    stepped = client.post("/api/v1/agents/missing-agent/step")
    reflected = client.post("/api/v1/agents/missing-agent/force-reflect")

    assert stepped.status_code == 404
    assert reflected.status_code == 404
    assert stepped.json() == {
        "error": "not_found",
        "message": "Unknown agent 'missing-agent'.",
    }
    assert reflected.json() == {
        "error": "not_found",
        "message": "Unknown agent 'missing-agent'.",
    }


def test_memory_routes_return_successful_responses_for_known_agent(client: TestClient) -> None:
    """Memory routes should respond successfully for a known authoritative agent."""

    client.post("/api/v1/agents/agent-1/force-reflect")

    episodes = client.get("/api/v1/memory/agent-1/episodes")
    beliefs = client.get("/api/v1/memory/agent-1/beliefs")
    candidates = client.get("/api/v1/memory/agent-1/daily-summary-candidates")
    retrieved = client.post("/api/v1/memory/agent-1/retrieve", json={"query": "Villager", "limit": 5})
    summary = client.post("/api/v1/memory/agent-1/summarize")

    assert episodes.status_code == 200
    assert beliefs.status_code == 200
    assert candidates.status_code == 200
    assert retrieved.status_code == 200
    assert summary.status_code == 200
    assert isinstance(episodes.json()["episodes"], list)
    assert isinstance(beliefs.json()["beliefs"], list)
    assert isinstance(candidates.json()["candidates"], list)
    assert retrieved.json()["agent_id"] == "agent-1"
    assert "memory_count" in summary.json()
    assert isinstance(EpisodesResponse.model_validate(episodes.json()), EpisodesResponse)
    assert isinstance(MemoryRetrieveResponse.model_validate(retrieved.json()), MemoryRetrieveResponse)
    assert isinstance(MemorySummarizeResponse.model_validate(summary.json()), MemorySummarizeResponse)


def test_memory_routes_return_not_found_for_missing_agent(client: TestClient) -> None:
    """Memory routes should return standardized not-found payloads for missing agents."""

    episodes = client.get("/api/v1/memory/missing-agent/episodes")
    beliefs = client.get("/api/v1/memory/missing-agent/beliefs")
    candidates = client.get("/api/v1/memory/missing-agent/daily-summary-candidates")
    retrieved = client.post("/api/v1/memory/missing-agent/retrieve", json={"query": "storm", "limit": 3})
    summary = client.post("/api/v1/memory/missing-agent/summarize")

    expected = {
        "error": "not_found",
        "message": "Unknown agent 'missing-agent'.",
    }
    assert episodes.status_code == 404
    assert beliefs.status_code == 404
    assert candidates.status_code == 404
    assert retrieved.status_code == 404
    assert summary.status_code == 404
    assert episodes.json() == expected
    assert beliefs.json() == expected
    assert candidates.json() == expected
    assert retrieved.json() == expected
    assert summary.json() == expected


def test_debug_routes_return_metrics_and_inspection_payloads(client: TestClient) -> None:
    """Debug routes should expose runtime metrics and inspection-friendly data."""

    client.post("/api/v1/agents/agent-1/force-reflect")
    metrics = client.get("/api/v1/debug/metrics")
    daily_metrics = client.get("/api/v1/debug/metrics/daily")
    replay = client.get("/api/v1/debug/replay")
    reflections = client.get("/api/v1/debug/reflections")
    inspect_agent = client.get("/api/v1/debug/inspect/agent/agent-1")
    inspect_household = client.get("/api/v1/debug/inspect/household/unknown-household")

    assert metrics.status_code == 200
    assert daily_metrics.status_code == 200
    assert replay.status_code == 200
    assert reflections.status_code == 200
    assert inspect_agent.status_code == 200
    assert inspect_household.status_code == 404

    assert {
        "tick",
        "sim_time",
        "total_recorded_ticks",
        "last_tick_event_types",
        "last_tick_event_type_counts",
        "latest_daily_metrics",
        "recent_daily_metrics",
    } <= set(metrics.json())
    assert {"current", "latest", "recent"} == set(daily_metrics.json())
    assert isinstance(replay.json()["events"], list)
    assert inspect_agent.json()["agent"]["agent_id"] == "agent-1"
    assert isinstance(DebugMetricsResponse.model_validate(metrics.json()), DebugMetricsResponse)
    assert isinstance(DailyMetricsDebugResponse.model_validate(daily_metrics.json()), DailyMetricsDebugResponse)
    assert isinstance(ReplayResponse.model_validate(replay.json()), ReplayResponse)
    assert isinstance(ReflectionRunsResponse.model_validate(reflections.json()), ReflectionRunsResponse)
    assert isinstance(AgentInspectResponse.model_validate(inspect_agent.json()), AgentInspectResponse)
    assert inspect_household.json() == {
        "error": "not_found",
        "message": "Unknown household 'unknown-household'.",
    }


def test_debug_daily_metrics_route_exposes_finalized_history_after_rollover(client: TestClient) -> None:
    """The daily debug metrics route should expose the latest finalized day plus recent history."""

    client.post("/api/v1/admin/reset-world")
    client.post("/api/v1/admin/advance-days/1")

    response = client.get("/api/v1/debug/metrics/daily?limit=3")

    assert response.status_code == 200
    payload = DailyMetricsDebugResponse.model_validate(response.json())
    assert payload.current is not None
    assert payload.latest is not None
    assert payload.recent
    assert payload.recent[-1].day_index == payload.latest.day_index


def test_debug_daily_metrics_route_exposes_current_preview_before_first_rollover(client: TestClient) -> None:
    """The daily debug metrics route should expose an in-progress day preview before finalization."""

    client.post("/api/v1/admin/reset-world")

    response = client.get("/api/v1/debug/metrics/daily?limit=3")

    assert response.status_code == 200
    payload = DailyMetricsDebugResponse.model_validate(response.json())
    assert payload.current is not None
    assert payload.latest is None
    assert payload.recent == []
    assert payload.current.population.total_population >= 1


def test_debug_inspect_agent_returns_clean_not_found_for_missing_agent(client: TestClient) -> None:
    """Agent inspection should return the standardized not-found payload for missing agents."""

    response = client.get("/api/v1/debug/inspect/agent/missing-agent")

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Unknown agent 'missing-agent'.",
    }


def test_admin_routes_reset_and_mutate_authoritative_state(client: TestClient) -> None:
    """Admin routes should expose simple authoritative world controls."""

    spawned_agent = client.post("/api/v1/admin/spawn-agent", json={"name": "Ayla", "tile_x": 2, "tile_y": 2})
    spawned_food = client.post(
        "/api/v1/admin/spawn-food",
        json={"tile_x": 2, "tile_y": 2, "quantity": 3, "item_type": "berries"},
    )
    advanced = client.post("/api/v1/admin/advance-days/2")
    reset = client.post("/api/v1/admin/reset-world")

    assert spawned_agent.status_code == 200
    assert spawned_food.status_code == 200
    assert advanced.status_code == 200
    assert reset.status_code == 200

    assert spawned_agent.json()["status"] == "spawned"
    assert spawned_agent.json()["agent"]["name"] == "Ayla"
    assert spawned_food.json()["item_type"] == "berries"
    assert advanced.json()["days_requested"] == 2
    assert advanced.json()["advance_mode"] == "clock_jump"
    assert advanced.json()["simulation_progressed"] is False
    assert reset.json()["status"] == "reset"
    assert isinstance(SpawnAgentResponse.model_validate(spawned_agent.json()), SpawnAgentResponse)
    assert isinstance(SpawnFoodResponse.model_validate(spawned_food.json()), SpawnFoodResponse)
    assert isinstance(AdvanceDaysResponse.model_validate(advanced.json()), AdvanceDaysResponse)
    assert isinstance(ResetWorldResponse.model_validate(reset.json()), ResetWorldResponse)


def test_admin_routes_reject_invalid_inputs_cleanly(client: TestClient) -> None:
    """Admin routes should reject invalid path and body payloads through validation."""

    invalid_food = client.post(
        "/api/v1/admin/spawn-food",
        json={"tile_x": 1, "tile_y": 1, "quantity": 0, "item_type": "berries"},
    )
    invalid_advance = client.post("/api/v1/admin/advance-days/0")

    assert invalid_food.status_code == 422
    assert invalid_food.json()["detail"][0]["loc"] == ["body", "quantity"]
    assert invalid_advance.status_code == 422
    assert invalid_advance.json()["detail"][0]["loc"] == ["path", "days"]


def test_query_validation_limits_are_enforced_on_list_endpoints(client: TestClient) -> None:
    """Query-param limits should be enforced on recent-events and replay endpoints."""

    invalid_events = client.get("/api/v1/world/events/recent?limit=0")
    invalid_replay = client.get("/api/v1/debug/replay?limit=101")
    invalid_retrieve = client.post("/api/v1/memory/agent-1/retrieve", json={"query": "storm", "limit": 21})

    assert invalid_events.status_code == 422
    assert invalid_replay.status_code == 422
    assert invalid_retrieve.status_code == 422
    assert invalid_events.json()["detail"][0]["loc"] == ["query", "limit"]
    assert invalid_replay.json()["detail"][0]["loc"] == ["query", "limit"]
    assert invalid_retrieve.json()["detail"][0]["loc"] == ["body", "limit"]


def test_request_validation_and_openapi_cleanup_are_visible(client: TestClient) -> None:
    """Tighter validation and shared error schemas should appear at the API boundary."""

    invalid_retrieve = client.post("/api/v1/memory/agent-1/retrieve", json={"query": "   ", "limit": 5})
    invalid_spawn = client.post("/api/v1/admin/spawn-agent", json={"name": "   ", "tile_x": 1, "tile_y": 1})
    openapi = client.get("/openapi.json")

    assert invalid_retrieve.status_code == 422
    assert invalid_spawn.status_code == 422
    assert openapi.status_code == 200

    openapi_payload = openapi.json()
    route_schema = openapi_payload["paths"]["/api/v1/agents/{agent_id}"]["get"]
    assert "404" in route_schema["responses"]
    assert (
        route_schema["responses"]["404"]["content"]["application/json"]["schema"]["$ref"]
        == "#/components/schemas/ErrorResponse"
    )
