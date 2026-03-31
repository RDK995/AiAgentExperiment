"""Phase 4 boundary and contract tests proving backend authority."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.reflection import ReflectionWorkflow
from app.cognition.reflection_graph import AutobiographyBuilder
from app.cognition.slow_loop import SlowLoopService
from app.cognition.validation import ReflectionValidationError, ReflectionValidator
from app.engine.event_bus import EventBus
from app.engine.sim_clock import SimTick
from app.engine.world_state import AgentState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.schemas.agent import AgentSnapshot
from app.schemas.api import MoveAgentRequest, SimulationSnapshot
from app.schemas.event import EventType, SimulationEvent
from app.schemas.reflection import ReflectionResult


def test_snapshot_contract_exposes_only_client_facing_state(client: TestClient) -> None:
    """Snapshot payloads should expose render/state views without authority fields."""

    payload = client.get("/api/v1/world/snapshot").json()

    assert set(payload.keys()) == {"tick", "world", "agents", "generated_at"}
    assert "memory" not in payload
    assert "beliefs" not in payload
    assert "relationships" not in payload
    assert "pregnancies" not in payload
    assert "cognition" not in payload

    for agent in payload["agents"]:
        assert set(agent.keys()) == {"agent_id", "name", "position", "needs", "current_action"}
        assert "inventory" not in agent
        assert "memories" not in agent
        assert "beliefs" not in agent
        assert "relationships" not in agent
        assert "pregnancy" not in agent
        assert "cognition" not in agent


def test_snapshot_schema_rejects_authority_fields_not_in_contract() -> None:
    """DTO validation should reject extra authority fields in client-facing snapshots."""

    illicit_payload = {
        "tick": 1,
        "world": {
            "width": 2,
            "height": 2,
            "tiles": [
                {"x": 0, "y": 0, "terrain": "grass", "walkable": True},
            ],
        },
        "agents": [
            {
                "agent_id": "agent-1",
                "name": "Villager 1",
                "position": {"x": 0, "y": 0},
                "needs": {"hunger": 1.0, "thirst": 2.0, "fatigue": 3.0},
                "current_action": "idle",
                "beliefs": ["should not be here"],
            }
        ],
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        SimulationSnapshot.model_validate(illicit_payload)
    except Exception as exc:
        error_text = str(exc)
    else:
        raise AssertionError("SimulationSnapshot unexpectedly accepted forbidden authority fields.")

    assert "beliefs" in error_text
    assert "extra_forbidden" in error_text


def test_agent_snapshot_schema_rejects_forbidden_authority_fields() -> None:
    """Agent DTO validation should reject cognitive or memory authority fields."""

    illicit_agent_payload = {
        "agent_id": "agent-1",
        "name": "Villager 1",
        "position": {"x": 1, "y": 1},
        "needs": {"hunger": 10.0, "thirst": 20.0, "fatigue": 30.0},
        "current_action": "rest",
        "memory": ["forbidden"],
    }

    try:
        AgentSnapshot.model_validate(illicit_agent_payload)
    except Exception as exc:
        error_text = str(exc)
    else:
        raise AssertionError("AgentSnapshot unexpectedly accepted forbidden authority fields.")

    assert "memory" in error_text
    assert "extra_forbidden" in error_text


def test_move_request_schema_rejects_extra_client_supplied_state() -> None:
    """Action request DTOs should reject extra client state injection attempts."""

    illicit_payload = {
        "agent_id": "agent-1",
        "target_x": 1,
        "target_y": 2,
        "inventory": {"berries": 999},
    }

    try:
        MoveAgentRequest.model_validate(illicit_payload)
    except Exception as exc:
        error_text = str(exc)
    else:
        raise AssertionError("MoveAgentRequest unexpectedly accepted extra client authority fields.")

    assert "inventory" in error_text
    assert "extra_forbidden" in error_text


def test_move_endpoint_rejects_extra_client_supplied_state(client: TestClient) -> None:
    """The API should reject move requests carrying extra state outside the contract."""

    response = client.post(
        "/api/v1/world/actions/move",
        json={
            "agent_id": "agent-1",
            "target_x": 1,
            "target_y": 6,
            "memory": ["client should not send this"],
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail[0]["type"] == "extra_forbidden"
    assert detail[0]["loc"] == ["body", "memory"]


def test_no_direct_slow_loop_write_bypasses_validation() -> None:
    """Invalid reflection results must not mutate authoritative slow-loop state."""

    class RejectingWorkflow(ReflectionWorkflow):
        def run(self, agent: AgentState, context) -> ReflectionResult:
            return ReflectionResult(
                goals=[""],
                beliefs=["invalid"],
                memory_entries=["invalid"],
                planner_hints=["rest_soon"],
            )

    world = WorldState(
        width=1,
        height=1,
        agents=[AgentState(agent_id="agent-1", name="Villager 1", x=0, y=0)],
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )
    world.agents[0].slow_loop_trigger_flags.add("major_life_event")
    tick = SimTick(
        tick=1,
        at=datetime(2000, 1, 2, 9, 0, tzinfo=timezone.utc),
        previous_day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        day_index=datetime(2000, 1, 2, tzinfo=timezone.utc).toordinal(),
    )
    event_bus = EventBus()
    slow_loop = SlowLoopService(
        memory_retriever=MemoryRetriever(),
        autobiography_builder=AutobiographyBuilder(),
        reflection_workflow=RejectingWorkflow(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )

    slow_loop.handle_post_fast_loop(world, tick, event_bus)
    replayed_events = event_bus.drain()

    assert slow_loop.last_results[0].applied is False
    assert world.agents[0].current_goal == "Maintain daily routine"
    assert world.agents[0].beliefs == []
    assert world.agents[0].memories == []
    assert world.agents[0].pending_planner_hints == []
    assert all(event.type is not EventType.SLOW_LOOP_COMPLETED for event in replayed_events)
