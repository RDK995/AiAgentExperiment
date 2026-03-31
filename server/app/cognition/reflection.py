"""Deterministic reflection workflow stubs for the agent slow loop."""

from __future__ import annotations

from app.engine.world_state import AgentState
from app.schemas.reflection import ReflectionContext, ReflectionResult


class ReflectionWorkflow:
    """Prototype reflection workflow returning structured placeholder outputs."""

    def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
        """Produce deterministic reflection outputs from structured context."""

        failure_hint = (
            ["reflect_on_failures", "rest_soon"]
            if "repeated_plan_failure" in context.trigger_reasons
            else ["keep_routine"]
        )
        return ReflectionResult(
            goals=[f"Support village stability for {agent.name}"],
            beliefs=[f"{agent.name} can improve outcomes by adapting routines"],
            memory_entries=[context.autobiography],
            planner_hints=failure_hint,
        )
