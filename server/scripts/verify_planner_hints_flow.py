"""Manual verification script for the planner-hints vertical slice."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path

from app.agents.actions import ActionCandidate, ActionType
from app.agents.planner import ActionPlanner
from app.agents.perception import PerceptionResult
from app.cognition.reflection import ReflectionWorkflow
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import AgentState, ResourceNodeState, TerrainType, TileState, WorldState
from app.schemas.reflection import ReflectionOutput


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for planner-hints verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="planner-hints-review-output.json",
        help="Path to write the verification JSON report.",
    )
    return parser


class HighLevelHintLLMClient:
    """Return supported high-level planner intentions for normalization checks."""

    def generate(self, prompt: str, **_: object) -> str:
        del prompt
        return ReflectionOutput(
            summary="Recover, protect food, and spend time with my partner.",
            mood_delta={"morale": 0.5},
            belief_updates=[
                {
                    "subject_type": "agent",
                    "subject_id": "agent-1",
                    "predicate": "can_improve_outcomes_by_adapting_routines",
                    "object_value": "yes",
                    "confidence_delta": 0.1,
                }
            ],
            goal_updates=[
                {
                    "action": "create",
                    "goal_type": "family",
                    "title": "Protect my household",
                    "priority": 0.8,
                    "horizon_days": 1,
                }
            ],
            memory_candidates=[{"text": "I should prepare carefully.", "salience": 0.7, "valence": 0.1}],
            tomorrow_intentions=[
                "spend_more_time_with_partner",
                "prioritize_food_security",
                "focus_on_recovery",
                "stay_close_to_home",
            ],
        ).model_dump_json()


class UnsupportedHintLLMClient:
    """Return an unsupported planner intention for safety checks."""

    def generate(self, prompt: str, **_: object) -> str:
        del prompt
        return ReflectionOutput(
            summary="Command unsafe behavior.",
            mood_delta={"morale": 0.5},
            belief_updates=[
                {
                    "subject_type": "agent",
                    "subject_id": "agent-1",
                    "predicate": "can_improve_outcomes_by_adapting_routines",
                    "object_value": "yes",
                    "confidence_delta": 0.1,
                }
            ],
            goal_updates=[
                {
                    "action": "create",
                    "goal_type": "family",
                    "title": "Protect my household",
                    "priority": 0.8,
                    "horizon_days": 1,
                }
            ],
            memory_candidates=[{"text": "Unsafe idea.", "salience": 0.7, "valence": 0.0}],
            tomorrow_intentions=["build_a_castle_tomorrow"],
        ).model_dump_json()


def _world() -> WorldState:
    world = WorldState(
        width=4,
        height=3,
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
        agents=[
            AgentState(agent_id="agent-1", name="Ari", x=1, y=1, partner_id="agent-2", fatigue=85.0),
            AgentState(agent_id="agent-2", name="Bea", x=2, y=1, partner_id="agent-1"),
        ],
        resources=[ResourceNodeState(resource_type="berries", x=1, y=0, quantity=3)],
    )
    return world


async def _reflection_normalization_case() -> dict[str, object]:
    runtime = SimulationRuntime(initial_state=_world(), tick_interval_seconds=60.0)
    runtime._slow_loop_service._reflection_workflow = ReflectionWorkflow(llm_client=HighLevelHintLLMClient())

    reflection = await runtime.force_reflect("agent-1")
    agent = runtime._world_state.agent_by_id("agent-1")
    assert agent is not None

    return {
        "force_reflect": reflection.model_dump(mode="json"),
        "pending_planner_hints": list(agent.pending_planner_hints),
        "checks": {
            "applied": reflection.applied is True,
            "normalized_hints": reflection.planner_hints == [
                "visit_partner",
                "prioritize_food_security",
                "focus_on_recovery",
                "stay_close_to_home",
            ],
            "stored_on_agent": agent.pending_planner_hints == [
                "visit_partner",
                "prioritize_food_security",
                "focus_on_recovery",
                "stay_close_to_home",
            ],
        },
        "runtime": runtime,
    }


async def _hint_consumption_case(runtime: SimulationRuntime) -> dict[str, object]:
    await runtime.step_once()
    debug_state = await runtime.get_debug_state()
    agent = runtime._world_state.agent_by_id("agent-1")
    assert agent is not None
    trace = debug_state["last_fast_loop_traces"][0]

    return {
        "last_fast_loop_trace": trace,
        "pending_planner_hints_after_tick": list(agent.pending_planner_hints),
        "checks": {
            "legal_action_selected": trace["selected_action"] in {"rest", "eat", "gather_food", "socialize", "court"},
            "recovery_hint_consumed": "focus_on_recovery" not in agent.pending_planner_hints,
            "other_hints_remain_bounded": agent.pending_planner_hints == [
                "visit_partner",
                "prioritize_food_security",
                "stay_close_to_home",
            ],
        },
    }


def _planner_interpretation_case() -> dict[str, object]:
    agent = AgentState(
        agent_id="agent-1",
        name="Ari",
        x=1,
        y=1,
        partner_id="agent-2",
        pending_planner_hints=["visit_partner", "prioritize_food_security"],
    )
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[
            ActionCandidate(action_type=ActionType.WANDER, score=15.0),
            ActionCandidate(action_type=ActionType.SOCIALIZE, score=15.0),
        ],
        perception=PerceptionResult(visible_agents=["agent-2"], visible_partner=True),
    )

    return {
        "selected_action": selected.action_type.value,
        "tasks": [task.to_payload() for task in selected.tasks],
        "checks": {
            "soft_bias_only": selected.action_type.value == "socialize"
            and selected.tasks[0]["task_type"] if False else True,
            "partner_targeted_legally": selected.tasks[0].metadata.get("target_agent_id") == "agent-2",
        },
    }


async def _unsupported_hint_case() -> dict[str, object]:
    runtime = SimulationRuntime(initial_state=_world(), tick_interval_seconds=60.0)
    runtime._slow_loop_service._reflection_workflow = ReflectionWorkflow(llm_client=UnsupportedHintLLMClient())

    reflection = await runtime.force_reflect("agent-1")
    agent = runtime._world_state.agent_by_id("agent-1")
    assert agent is not None

    return {
        "force_reflect": reflection.model_dump(mode="json"),
        "pending_planner_hints": list(agent.pending_planner_hints),
        "checks": {
            "failed_safely": reflection.applied is False and reflection.failure_stage == "validate",
            "no_hints_stored": agent.pending_planner_hints == [],
        },
    }


async def build_report() -> dict[str, object]:
    """Run compact end-to-end verification against the planner-hints flow."""

    reflection_normalization = await _reflection_normalization_case()
    runtime = reflection_normalization.pop("runtime")
    hint_consumption = await _hint_consumption_case(runtime)
    planner_interpretation = _planner_interpretation_case()
    unsupported_hint = await _unsupported_hint_case()

    planner_interpretation["checks"]["soft_bias_only"] = (
        planner_interpretation["selected_action"] == "socialize"
        and planner_interpretation["tasks"][0]["task_type"] == "socialize"
    )

    checks = {
        **{f"reflection_normalization.{key}": value for key, value in reflection_normalization["checks"].items()},
        **{f"hint_consumption.{key}": value for key, value in hint_consumption["checks"].items()},
        **{f"planner_interpretation.{key}": value for key, value in planner_interpretation["checks"].items()},
        **{f"unsupported_hint.{key}": value for key, value in unsupported_hint["checks"].items()},
    }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "reflection_normalization": reflection_normalization,
        "hint_consumption": hint_consumption,
        "planner_interpretation": planner_interpretation,
        "unsupported_hint": unsupported_hint,
    }


def main() -> int:
    """Run verification and write a JSON report to disk."""

    parser = build_parser()
    args = parser.parse_args()
    report = asyncio.run(build_report())
    output_path = Path(args.output).resolve()
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
