"""Manual verification script for the planner->executor->event action catalog flow."""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path

from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import AgentState, ResourceNodeState, TerrainType, TileState, WorldState


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for action-catalog verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="action-catalog-review-output.json",
        help="Path to write the verification JSON report.",
    )
    return parser


async def _run_survival_case() -> dict[str, object]:
    """Exercise a direct survival action through the real runtime."""

    world = WorldState(
        width=3,
        height=3,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(3) for x in range(3)],
        agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1, thirst=90.0)],
        resources=[ResourceNodeState(resource_type="water", x=1, y=1, quantity=2)],
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )
    runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

    snapshot = await runtime.step_once()
    debug_state = await runtime.get_debug_state()
    trace = debug_state["last_fast_loop_traces"][0]

    return {
        "selected_action": trace["selected_action"],
        "planned_tasks": trace["planned_tasks"],
        "emitted_event_types": trace["emitted_event_types"],
        "snapshot_current_action": snapshot.agents[0].current_action,
        "snapshot_needs": snapshot.agents[0].needs.model_dump(mode="json"),
        "checks": {
            "selected_action_is_drink": trace["selected_action"] == "drink",
            "planner_selected_concrete_drink_task": trace["planned_tasks"] == ["fetch_water", "drink"],
            "agent_drank_event_emitted": "agent_drank" in trace["emitted_event_types"],
            "snapshot_exposes_current_action": snapshot.agents[0].current_action == "drink",
        },
    }


async def _run_social_case() -> dict[str, object]:
    """Exercise a concrete social plan through the real runtime."""

    world = WorldState(
        width=3,
        height=3,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(3) for x in range(3)],
        agents=[
            AgentState(agent_id="agent-1", name="A", x=1, y=1, loneliness=90.0),
            AgentState(agent_id="agent-2", name="B", x=1, y=2),
        ],
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )
    runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

    snapshot = await runtime.step_once()
    debug_state = await runtime.get_debug_state()
    trace = debug_state["last_fast_loop_traces"][0]

    return {
        "selected_action": trace["selected_action"],
        "planned_tasks": trace["planned_tasks"],
        "emitted_event_types": trace["emitted_event_types"],
        "snapshot_current_action": snapshot.agents[0].current_action,
        "loneliness_after_tick": runtime._world_state.agents[0].loneliness,
        "checks": {
            "selected_action_is_socialize": trace["selected_action"] == "socialize",
            "planner_selected_concrete_social_chain": trace["planned_tasks"] == ["greet", "talk"],
            "social_milestone_emitted": "social_milestone" in trace["emitted_event_types"],
            "snapshot_exposes_current_action": snapshot.agents[0].current_action == "socialize",
            "execution_reduced_loneliness": runtime._world_state.agents[0].loneliness < 90.0,
        },
    }


async def build_report() -> dict[str, object]:
    """Run the representative verification cases and assemble a JSON-safe report."""

    survival = await _run_survival_case()
    social = await _run_social_case()
    combined_checks = {
        "survival_path_validated": all(bool(value) for value in survival["checks"].values()),
        "social_path_validated": all(bool(value) for value in social["checks"].values()),
    }
    combined_checks["all_checks_passed"] = all(combined_checks.values())

    return {
        "checks": combined_checks,
        "survival_case": survival,
        "social_case": social,
    }


def main() -> None:
    """Run the verification and write the JSON report to disk."""

    parser = build_parser()
    args = parser.parse_args()
    report = asyncio.run(build_report())
    output_path = Path(args.output)
    output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(output_path)


if __name__ == "__main__":
    main()
