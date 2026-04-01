"""Deterministic reflection workflow stubs for the agent slow loop."""

from __future__ import annotations

from app.cognition.output_parser import ReflectionOutputParser
from app.engine.world_state import AgentState
from app.schemas.reflection import (
    BeliefUpdate,
    GoalUpdate,
    MemoryCandidate,
    ReflectionContext,
    ReflectionOutput,
    ReflectionResult,
)
from app.db.enums import GoalType


class ReflectionWorkflow:
    """Prototype reflection workflow returning structured placeholder outputs."""

    def __init__(self, output_parser: ReflectionOutputParser | None = None) -> None:
        self._output_parser = output_parser or ReflectionOutputParser()

    def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
        """Produce deterministic reflection outputs from structured context."""

        goal_type = GoalType.SAFETY if "major_life_event" in context.trigger_reasons else GoalType.FAMILY
        structured_output = ReflectionOutput(
            summary=f"Reflection summary for {agent.name}",
            mood_delta={"morale": -1.0 if "repeated_plan_failure" in context.trigger_reasons else 0.5},
            belief_updates=[
                BeliefUpdate(
                    subject_type="agent",
                    subject_id=agent.agent_id,
                    predicate="can_improve_outcomes_by_adapting_routines",
                    object_value="yes",
                    confidence_delta=0.2,
                )
            ],
            goal_updates=[
                GoalUpdate(
                    action="create",
                    goal_type=goal_type,
                    title=f"Support village stability for {agent.name}",
                    priority=1.0,
                    horizon_days=1,
                )
            ],
            memory_candidates=[
                MemoryCandidate(
                    text=context.autobiography,
                    salience=0.8,
                    valence=0.1,
                )
            ],
            tomorrow_intentions=(
                ["reflect_on_failures", "rest_soon"]
                if "repeated_plan_failure" in context.trigger_reasons
                else ["keep_routine"]
            ),
        )
        return self._output_parser.parse(structured_output)
