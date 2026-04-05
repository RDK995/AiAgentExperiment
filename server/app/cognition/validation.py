"""Validation for structured reflection outputs before state mutation."""

from __future__ import annotations

import uuid

from app.agents.planner_hints import normalize_planner_hints
from app.engine.world_state import AgentState, WorldState
from app.schemas.reflection import ReflectionOutput, ReflectionResult


class ReflectionValidationError(ValueError):
    """Raised when reflection outputs fail validation."""


class ReflectionValidator:
    """Validate reflection outputs before applying them to agent state."""

    def validate(self, result: ReflectionResult) -> ReflectionResult:
        """Ensure outputs are structured, bounded, and non-empty."""

        for field_name in ("goals", "beliefs", "memory_entries", "planner_hints"):
            values = getattr(result, field_name)
            if not values:
                raise ReflectionValidationError(f"{field_name} must contain at least one entry.")
            if len(values) > 5:
                raise ReflectionValidationError(f"{field_name} exceeded maximum length.")
            if any(not value.strip() for value in values):
                raise ReflectionValidationError(f"{field_name} contains empty entries.")

        return result

    def validate_output(
        self,
        output: ReflectionOutput,
        *,
        agent: AgentState,
        world: WorldState,
    ) -> ReflectionOutput:
        """Validate structured reflection output against world and safety constraints."""

        self._validate_mood_delta(output.mood_delta)
        self._validate_belief_updates(output, world)
        self._validate_goal_volume(output)
        output.tomorrow_intentions = self._validate_planner_hints(output, agent, world)
        self.validate(output.to_reflection_result())
        return output

    @staticmethod
    def _validate_mood_delta(mood_delta: dict[str, float]) -> None:
        allowed_keys = {"morale", "hope", "grief", "shame"}
        for key, value in mood_delta.items():
            if key not in allowed_keys:
                raise ReflectionValidationError(f"Unsupported mood field '{key}'.")
            if value < -10.0 or value > 10.0:
                raise ReflectionValidationError(f"Mood delta for '{key}' is out of bounds.")

    @staticmethod
    def _validate_goal_volume(output: ReflectionOutput) -> None:
        if len(output.goal_updates) > 3:
            raise ReflectionValidationError("Too many goal updates in one reflection pass.")
        for update in output.goal_updates:
            if update.priority > 1.0:
                raise ReflectionValidationError("Goal priority must stay within 0 and 1.")

    @staticmethod
    def _validate_belief_updates(output: ReflectionOutput, world: WorldState) -> None:
        known_agent_ids = {agent.agent_id for agent in world.agents}
        forbidden_kinship_predicates = {
            "is_parent_of",
            "is_child_of",
            "is_sibling_of",
            "is_partner_of",
            "shares_household_with",
        }
        known_item_types = {item.item_type for item in world.items}
        known_resource_types = {resource.resource_type for resource in world.resources}

        for update in output.belief_updates:
            if update.predicate in forbidden_kinship_predicates:
                raise ReflectionValidationError("Reflection cannot mutate kinship facts.")
            if (
                update.subject_type == "agent"
                and update.subject_id is not None
                and update.subject_id not in known_agent_ids
                and not _is_uuid_string(update.subject_id)
            ):
                raise ReflectionValidationError("Reflection referenced an unknown agent.")
            if update.subject_type == "item" and update.object_value not in known_item_types:
                raise ReflectionValidationError("Reflection invented an unknown item.")
            if update.subject_type == "resource" and update.object_value not in known_resource_types:
                raise ReflectionValidationError("Reflection invented an unknown resource.")
            if update.subject_type == "building":
                raise ReflectionValidationError("Reflection cannot invent buildings.")

    @staticmethod
    def _validate_planner_hints(output: ReflectionOutput, agent: AgentState, world: WorldState) -> list[str]:
        try:
            normalized = normalize_planner_hints(output.tomorrow_intentions, agent=agent, world=world)
        except ValueError as exc:
            raise ReflectionValidationError(str(exc)) from exc

        for hint in normalized:
            if hint == "visit_partner" and agent.partner_id is None:
                raise ReflectionValidationError("visit_partner requires a current partner.")
            if hint == "gather_resources" and not world.resources:
                raise ReflectionValidationError("gather_resources requires known resources.")
        return normalized


def _is_uuid_string(value: str) -> bool:
    try:
        uuid.UUID(str(value))
    except ValueError:
        return False
    return True
