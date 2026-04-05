"""Integration tests for authoritative FastAPI world endpoints."""

from fastapi.testclient import TestClient


def _without_generated_at(payload: dict) -> dict:
    """Strip non-deterministic snapshot metadata for stable comparisons."""

    return {key: value for key, value in payload.items() if key != "generated_at"}


def test_get_snapshot_endpoint_returns_consistent_schema(client: TestClient) -> None:
    """The snapshot endpoint should expose the authoritative world schema."""

    response = client.get("/api/v1/world/snapshot")

    assert response.status_code == 200
    payload = response.json()

    assert set(payload.keys()) == {"tick", "world", "agents", "generated_at"}
    assert payload["tick"] == 0
    assert set(payload["world"].keys()) == {"width", "height", "tiles"}
    assert payload["world"]["width"] == 16
    assert payload["world"]["height"] == 12
    assert len(payload["world"]["tiles"]) == 16 * 12
    assert len(payload["agents"]) == 3

    first_tile = payload["world"]["tiles"][0]
    assert set(first_tile.keys()) == {"x", "y", "terrain", "walkable"}

    first_agent = payload["agents"][0]
    assert set(first_agent.keys()) == {
        "agent_id",
        "name",
        "position",
        "needs",
        "current_action",
        "stage_of_life",
        "household_id",
        "partner_id",
        "current_goal",
    }
    assert set(first_agent["position"].keys()) == {"x", "y"}
    assert set(first_agent["needs"].keys()) == {"hunger", "thirst", "fatigue"}


def test_get_state_endpoint_matches_snapshot_endpoint(client: TestClient) -> None:
    """State and snapshot endpoints should expose the same authoritative model."""

    snapshot_response = client.get("/api/v1/world/snapshot")
    state_response = client.get("/api/v1/world/state")

    assert snapshot_response.status_code == 200
    assert state_response.status_code == 200
    assert _without_generated_at(snapshot_response.json()) == _without_generated_at(
        state_response.json()
    )


def test_post_tick_endpoint_advances_authoritative_state(client: TestClient) -> None:
    """A tick request should mutate server-owned state across requests."""

    before = client.get("/api/v1/world/snapshot").json()
    after = client.post("/api/v1/world/tick").json()

    assert after["tick"] == before["tick"] + 1
    assert after["agents"][0]["position"]["x"] != before["agents"][0]["position"]["x"]
    assert after["agents"][0]["needs"]["hunger"] > before["agents"][0]["needs"]["hunger"]
    assert after["agents"][0]["needs"]["thirst"] > before["agents"][0]["needs"]["thirst"]
    assert after["agents"][0]["needs"]["fatigue"] > before["agents"][0]["needs"]["fatigue"]


def test_post_run_endpoint_advances_multiple_ticks(client: TestClient) -> None:
    """The run endpoint should advance the simulation deterministically by N ticks."""

    before = client.get("/api/v1/world/snapshot").json()
    after = client.post("/api/v1/world/run", json={"ticks": 3}).json()
    latest = client.get("/api/v1/world/snapshot").json()

    assert after["tick"] == before["tick"] + 3
    assert latest["tick"] == after["tick"]
    assert _without_generated_at(latest) == _without_generated_at(after)


def test_post_move_action_updates_state_for_legal_move(client: TestClient) -> None:
    """A legal movement action should update only authoritative backend state."""

    before = client.get("/api/v1/world/snapshot").json()
    agent = before["agents"][0]

    response = client.post(
        "/api/v1/world/actions/move",
        json={
            "agent_id": agent["agent_id"],
            "target_x": agent["position"]["x"] - 1,
            "target_y": agent["position"]["y"],
        },
    )

    assert response.status_code == 200
    payload = response.json()

    assert payload["tick"] == before["tick"]
    assert payload["agents"][0]["position"]["x"] == agent["position"]["x"] - 1
    assert payload["agents"][0]["position"]["y"] == agent["position"]["y"]
    assert payload["agents"][0]["current_action"] == "walking"


def test_post_move_action_rejects_invalid_action_without_mutating_state(
    client: TestClient,
) -> None:
    """Illegal movement requests should be rejected and leave state unchanged."""

    before = client.get("/api/v1/world/snapshot").json()
    agent = before["agents"][0]

    response = client.post(
        "/api/v1/world/actions/move",
        json={
            "agent_id": agent["agent_id"],
            "target_x": agent["position"]["x"],
            "target_y": agent["position"]["y"] - 2,
        },
    )

    assert response.status_code == 409
    assert response.json() == {
        "error": "conflict",
        "message": "Illegal move for current world state.",
    }

    after = client.get("/api/v1/world/snapshot").json()
    assert _without_generated_at(after) == _without_generated_at(before)


def test_post_move_action_rejects_unknown_agent(client: TestClient) -> None:
    """Requests for unknown agents should return a not-found API error."""

    response = client.post(
        "/api/v1/world/actions/move",
        json={
            "agent_id": "missing-agent",
            "target_x": 0,
            "target_y": 0,
        },
    )

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Unknown agent 'missing-agent'.",
    }


def test_run_endpoint_rejects_invalid_request_schema(client: TestClient) -> None:
    """Invalid run payloads should be rejected at the API contract layer."""

    response = client.post("/api/v1/world/run", json={"ticks": 0})

    assert response.status_code == 422
    payload = response.json()
    assert payload["detail"][0]["loc"] == ["body", "ticks"]


def test_get_seed_definition_endpoint_returns_v1_village_layout(client: TestClient) -> None:
    """The backend should expose the deterministic v1 village seed for Godot bootstrap."""

    response = client.get("/api/v1/world/seeds/v1_village")

    assert response.status_code == 200
    payload = response.json()

    assert payload["seed_id"] == "v1_village"
    assert payload["world"]["width"] == 64
    assert payload["world"]["height"] == 64
    assert len(payload["world"]["structures"]) == 15
    assert len(payload["world"]["markers"]) == 3
    assert len(payload["agents"]) == 20
    assert len(payload["households"]) == 4


def test_seed_definition_endpoint_matches_client_bootstrap_assumptions(client: TestClient) -> None:
    """The seed definition route should preserve the building, marker, and social contract expected by Godot."""

    payload = client.get("/api/v1/world/seeds/v1_village").json()

    structures_by_type = {}
    for structure in payload["world"]["structures"]:
        structures_by_type[structure["structure_type"]] = (
            structures_by_type.get(structure["structure_type"], 0) + 1
        )
    markers_by_type = {marker["marker_type"]: marker for marker in payload["world"]["markers"]}
    social_kinds = [link["kind"] for link in payload["social_links"]]
    agent_ids = {agent["agent_id"] for agent in payload["agents"]}

    assert structures_by_type == {
        "village_center": 1,
        "house": 6,
        "well": 1,
        "farm_plot": 4,
        "storage_hut": 1,
        "cooking_area": 1,
        "graveyard": 1,
    }
    assert set(markers_by_type) == {"forest", "berries", "river_edge"}
    assert markers_by_type["forest"]["y"] < 10
    assert markers_by_type["berries"]["x"] < 10
    assert social_kinds.count("bonded_pair") == 2
    assert social_kinds.count("widowed_elder") == 1
    assert social_kinds.count("rival_pair") == 1
    assert social_kinds.count("close_friends") == 2
    for household in payload["households"]:
        assert household["home_structure_id"]
        assert set(household["member_ids"]) <= agent_ids


def test_seed_endpoint_can_reset_world_to_v1_village(client: TestClient) -> None:
    """Reseeding to v1 should rebuild the authoritative runtime around the fixed client seed."""

    response = client.post("/api/v1/world/seed", json={"seed_id": "v1_village"})

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "seeded"
    assert payload["seed_id"] == "v1_village"
    assert payload["width"] == 64
    assert payload["height"] == 64
    assert payload["seeded_agents"] == 20

    snapshot = client.get("/api/v1/world/snapshot").json()

    assert snapshot["world"]["width"] == 64
    assert snapshot["world"]["height"] == 64
    assert len(snapshot["agents"]) == 20


def test_seed_endpoint_reseeding_to_v1_is_deterministic(client: TestClient) -> None:
    """Repeated reseeds to the fixed v1 scenario should produce the same authoritative state."""

    first_seed = client.post("/api/v1/world/seed", json={"seed_id": "v1_village"})
    first_snapshot = client.get("/api/v1/world/snapshot").json()

    client.post("/api/v1/world/tick")

    second_seed = client.post("/api/v1/world/seed", json={"seed_id": "v1_village"})
    second_snapshot = client.get("/api/v1/world/snapshot").json()

    assert first_seed.status_code == 200
    assert second_seed.status_code == 200
    assert _without_generated_at(first_snapshot) == _without_generated_at(second_snapshot)


def test_seed_definition_endpoint_rejects_unknown_seed_cleanly(client: TestClient) -> None:
    """Unknown seed definitions should fail clearly for bootstrap clients."""

    response = client.get("/api/v1/world/seeds/missing_seed")

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Unknown world seed 'missing_seed'.",
    }
