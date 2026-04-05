"""Stubbed reflection client for deterministic prototype behavior."""

from __future__ import annotations

from app.db.enums import GoalType
from app.engine.world_state import AgentState
from app.schemas.reflection import (
    BeliefUpdate,
    GoalUpdate,
    MemoryCandidate,
    ReflectionContext,
    ReflectionOutput,
)


class ReflectionLLMClient:
    """Deterministic placeholder for future model-backed reflection."""

    def generate(
        self,
        prompt: str,
        *,
        agent: AgentState | None = None,
        context: ReflectionContext | None = None,
    ) -> str:
        """Return deterministic structured JSON for prototype reflection flows."""

        del prompt
        if agent is None or context is None:
            output = ReflectionOutput(
                summary="Reflection summary",
                mood_delta={"morale": 0.5},
                goal_updates=[],
                belief_updates=[],
                memory_candidates=[],
                tomorrow_intentions=["keep_routine"],
            )
            return output.model_dump_json()

        goal_type = GoalType.SAFETY if "repeated_plan_failure" in context.trigger_reasons else GoalType.FAMILY
        primary_goal = context.goals[0] if context.goals else f"Support village stability for {agent.name}"
        primary_memory = context.recent_events[0] if context.recent_events else context.autobiography
        belief_updates = [
            BeliefUpdate(
                subject_type="agent",
                subject_id=agent.agent_id,
                predicate="can_improve_outcomes_by_adapting_routines",
                object_value="yes",
                confidence_delta=0.2,
            )
        ]
        if context.relationships:
            belief_updates.append(
                BeliefUpdate(
                    subject_type="agent",
                    subject_id=context.relationships[0],
                    predicate="is_part_of_my_support_network",
                    object_value="yes",
                    confidence_delta=0.15,
                )
            )
        if "repeated_plan_failure" in context.trigger_reasons:
            intentions = ["reflect_on_failures", "rest_soon"]
            mood_delta = {"morale": -1.0}
        elif "severe_hunger_or_injury" in context.trigger_reasons:
            intentions = ["focus_on_recovery", "prioritize_food_security"]
            mood_delta = {"morale": -0.5}
        else:
            intentions = ["keep_routine"]
            mood_delta = {"morale": 0.5}

        output = ReflectionOutput(
            summary=f"Reflection summary for {agent.name}",
            mood_delta=mood_delta,
            belief_updates=belief_updates,
            goal_updates=[
                GoalUpdate(
                    action="create",
                    goal_type=goal_type,
                    title=primary_goal,
                    priority=1.0,
                    horizon_days=1,
                )
            ],
            memory_candidates=[
                MemoryCandidate(
                    text=primary_memory,
                    salience=0.85 if context.recent_events else 0.8,
                    valence=0.1,
                )
            ],
            tomorrow_intentions=intentions,
        )
        return output.model_dump_json()
