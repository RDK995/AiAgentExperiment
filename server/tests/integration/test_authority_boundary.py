"""Integration tests that enforce the backend/client authority boundary."""

from fastapi.testclient import TestClient


def _without_generated_at(payload: dict) -> dict:
    """Strip dynamic snapshot metadata for stable authority comparisons."""

    return {key: value for key, value in payload.items() if key != "generated_at"}


def test_backend_snapshot_is_authoritative_source_of_truth(client: TestClient) -> None:
    """Repeated reads should reflect only backend-owned state transitions."""

    before = client.get("/api/v1/world/snapshot").json()
    client.post("/api/v1/world/tick")
    after = client.get("/api/v1/world/snapshot").json()

    assert before["tick"] == 0
    assert after["tick"] == 1
    assert after["agents"][0]["position"] != before["agents"][0]["position"]


def test_client_cannot_mutate_authoritative_state_through_snapshot_requests(
    client: TestClient,
) -> None:
    """Client payloads on read endpoints must not override backend world state."""

    before = client.request(
        "GET",
        "/api/v1/world/state",
        json={
            "tick": 999,
            "agents": [
                {
                    "agent_id": "agent-1",
                    "position": {"x": 99, "y": 99},
                }
            ],
        },
    ).json()
    after = client.get("/api/v1/world/state").json()

    assert before["tick"] == 0
    assert before["agents"][0]["position"] != {"x": 99, "y": 99}
    assert _without_generated_at(after) == _without_generated_at(before)


def test_snapshot_schema_is_only_client_facing_state_contract(client: TestClient) -> None:
    """The API should expose only snapshot fields intended for the presentation layer."""

    payload = client.get("/api/v1/world/snapshot").json()

    assert set(payload.keys()) == {"tick", "world", "agents", "generated_at"}
    assert "inventories" not in payload
    assert "memory" not in payload
    assert "relationships" not in payload
    assert "pregnancies" not in payload
    assert "cognition" not in payload

    for agent in payload["agents"]:
        assert set(agent.keys()) == {
            "agent_id",
            "name",
            "position",
            "needs",
            "current_action",
        }
        assert "inventory" not in agent
        assert "memory" not in agent
        assert "relationships" not in agent
        assert "pregnancy" not in agent
        assert "cognition" not in agent


def test_illegal_actions_are_rejected_server_side(client: TestClient) -> None:
    """The backend must validate and reject illegal actions before mutating state."""

    before = client.get("/api/v1/world/snapshot").json()
    agent = before["agents"][0]

    response = client.post(
        "/api/v1/world/actions/move",
        json={
            "agent_id": agent["agent_id"],
            "target_x": agent["position"]["x"] + 8,
            "target_y": agent["position"]["y"],
        },
    )

    assert response.status_code == 409
    assert response.json() == {"detail": "Illegal move for current world state."}

    after = client.get("/api/v1/world/snapshot").json()
    assert _without_generated_at(after) == _without_generated_at(before)
