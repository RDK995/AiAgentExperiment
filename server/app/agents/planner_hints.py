"""Planner-hint normalization and interpretation helpers."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import re

from app.agents.actions import ActionCandidate, ActionType, PlannedTask, TaskType
from app.agents.perception import PerceptionResult
from app.engine.world_state import AgentState, WorldState


class PlannerHintKind(str, Enum):
    """Supported normalized planner hint categories."""

    KEEP_ROUTINE = "keep_routine"
    VISIT_PARTNER = "visit_partner"
    PRIORITIZE_FOOD_SECURITY = "prioritize_food_security"
    FOCUS_ON_RECOVERY = "focus_on_recovery"
    GATHER_RESOURCES = "gather_resources"
    EAT_SOON = "eat_soon"
    DRINK_SOON = "drink_soon"
    REST_SOON = "rest_soon"
    REFLECT_ON_FAILURES = "reflect_on_failures"
    IMPROVE_SOCIAL_STANDING = "improve_social_standing"
    CARE_FOR_CHILD_MORE = "care_for_child_more"
    REDUCE_CONFLICT = "reduce_conflict"
    PREPARE_FOR_WINTER = "prepare_for_winter"
    STAY_CLOSE_TO_HOME = "stay_close_to_home"
    AVOID_AGENT = "avoid_agent"


@dataclass(slots=True)
class PlannerHint:
    """Normalized planner hint with optional target agent."""

    kind: PlannerHintKind
    raw: str
    target_agent_id: str | None = None

    @property
    def canonical(self) -> str:
        """Return the canonical string stored on authoritative agent state."""

        if self.kind is PlannerHintKind.AVOID_AGENT and self.target_agent_id is not None:
            return f"avoid_agent_{self.target_agent_id}"
        return self.kind.value


_LITERAL_ALIASES: dict[str, PlannerHintKind] = {
    "keep_routine": PlannerHintKind.KEEP_ROUTINE,
    "visit_partner": PlannerHintKind.VISIT_PARTNER,
    "spend_more_time_with_partner": PlannerHintKind.VISIT_PARTNER,
    "prioritize_food_security": PlannerHintKind.PRIORITIZE_FOOD_SECURITY,
    "focus_on_recovery": PlannerHintKind.FOCUS_ON_RECOVERY,
    "gather_resources": PlannerHintKind.GATHER_RESOURCES,
    "eat_soon": PlannerHintKind.EAT_SOON,
    "drink_soon": PlannerHintKind.DRINK_SOON,
    "rest_soon": PlannerHintKind.REST_SOON,
    "reflect_on_failures": PlannerHintKind.REFLECT_ON_FAILURES,
    "improve_social_standing": PlannerHintKind.IMPROVE_SOCIAL_STANDING,
    "care_for_child_more": PlannerHintKind.CARE_FOR_CHILD_MORE,
    "reduce_conflict": PlannerHintKind.REDUCE_CONFLICT,
    "prepare_for_winter": PlannerHintKind.PREPARE_FOR_WINTER,
    "stay_close_to_home": PlannerHintKind.STAY_CLOSE_TO_HOME,
}

_AVOID_PATTERN = re.compile(r"^avoid_(.+?)_when_possible$")
_CANONICAL_AVOID_PATTERN = re.compile(r"^avoid_agent_(.+)$")


def normalize_planner_hints(raw_hints: list[str], *, agent: AgentState, world: WorldState) -> list[str]:
    """Normalize raw reflection intentions into canonical planner-consumable strings."""

    normalized: list[str] = []
    seen: set[str] = set()
    for raw_hint in raw_hints:
        hint = parse_planner_hint(raw_hint, agent=agent, world=world)
        canonical = hint.canonical
        if canonical not in seen:
            normalized.append(canonical)
            seen.add(canonical)
    return normalized


def parse_planner_hint(raw_hint: str, *, agent: AgentState, world: WorldState) -> PlannerHint:
    """Parse one raw hint string into a normalized planner hint."""

    value = raw_hint.strip()
    canonical_literal = _LITERAL_ALIASES.get(value)
    if canonical_literal is not None:
        return PlannerHint(kind=canonical_literal, raw=raw_hint)

    canonical_avoid = _CANONICAL_AVOID_PATTERN.match(value)
    if canonical_avoid:
        target_agent_id = canonical_avoid.group(1)
        if world.agent_by_id(target_agent_id) is None:
            raise ValueError("avoid_agent hint referenced an unknown agent.")
        return PlannerHint(kind=PlannerHintKind.AVOID_AGENT, raw=raw_hint, target_agent_id=target_agent_id)

    avoid_match = _AVOID_PATTERN.match(_slugify(value))
    if avoid_match:
        target_agent_id = _resolve_agent_reference(avoid_match.group(1), world)
        if target_agent_id is None:
            raise ValueError("avoid hint referenced an unknown agent.")
        return PlannerHint(kind=PlannerHintKind.AVOID_AGENT, raw=raw_hint, target_agent_id=target_agent_id)

    raise ValueError(f"Unsupported planner hint '{raw_hint}'.")


def interpret_planner_hints(raw_hints: list[str]) -> list[PlannerHint]:
    """Interpret already-normalized stored hints for planner/runtime usage."""

    interpreted: list[PlannerHint] = []
    for raw_hint in raw_hints:
        canonical = raw_hint.strip()
        kind = _LITERAL_ALIASES.get(canonical)
        if kind is not None:
            interpreted.append(PlannerHint(kind=kind, raw=raw_hint))
            continue
        match = _CANONICAL_AVOID_PATTERN.match(canonical)
        if match:
            interpreted.append(
                PlannerHint(
                    kind=PlannerHintKind.AVOID_AGENT,
                    raw=raw_hint,
                    target_agent_id=match.group(1),
                )
            )
    return interpreted


def rerank_candidates_with_hints(
    agent: AgentState,
    candidates: list[ActionCandidate],
    perception: PerceptionResult | None,
) -> list[ActionCandidate]:
    """Bias action candidate ordering using normalized planner hints without bypassing legality."""

    interpreted_hints = interpret_planner_hints(agent.pending_planner_hints)
    if not interpreted_hints:
        return candidates

    visible_agents = set(perception.visible_agents) if perception is not None else set()
    adjusted: list[ActionCandidate] = []
    for candidate in candidates:
        adjusted_score = candidate.score + _candidate_hint_bonus(
            candidate.action_type,
            interpreted_hints,
            agent=agent,
            visible_agents=visible_agents,
        )
        adjusted.append(ActionCandidate(action_type=candidate.action_type, score=round(adjusted_score, 3)))
    return sorted(adjusted, key=lambda item: (-item.score, item.action_type.value))


def enrich_tasks_with_hints(
    tasks: list[PlannedTask],
    *,
    objective: str,
    agent: AgentState,
) -> list[PlannedTask]:
    """Annotate legal tasks with planner-hint metadata for downstream debugging and interpretation."""

    interpreted_hints = interpret_planner_hints(agent.pending_planner_hints)
    if not interpreted_hints:
        return tasks

    active_hint_names = [hint.canonical for hint in interpreted_hints]
    avoid_ids = [hint.target_agent_id for hint in interpreted_hints if hint.kind is PlannerHintKind.AVOID_AGENT]
    target_partner = any(hint.kind is PlannerHintKind.VISIT_PARTNER for hint in interpreted_hints)
    for task in tasks:
        if active_hint_names:
            task.metadata.setdefault("planner_hints", list(active_hint_names))
        if avoid_ids:
            task.metadata.setdefault("avoid_agent_ids", [target for target in avoid_ids if target is not None])
        if target_partner and objective in {"socialize", "court"} and agent.partner_id is not None:
            task.metadata.setdefault("target_agent_id", agent.partner_id)
    return tasks


def consume_planner_hints_for_action(
    raw_hints: list[str],
    *,
    selected_action: str,
    perception: PerceptionResult | None,
) -> list[str]:
    """Consume one matching hint after it influences a selected legal action."""

    interpreted_hints = interpret_planner_hints(raw_hints)
    visible_agents = set(perception.visible_agents) if perception is not None else set()
    remaining = list(raw_hints)
    for hint in interpreted_hints:
        if _hint_matches_action(hint, selected_action=selected_action, visible_agents=visible_agents):
            remaining.remove(hint.canonical)
            break
    return remaining


def _candidate_hint_bonus(
    action_type: ActionType,
    hints: list[PlannerHint],
    *,
    agent: AgentState,
    visible_agents: set[str],
) -> float:
    bonus = 0.0
    for hint in hints:
        if hint.kind is PlannerHintKind.VISIT_PARTNER and agent.partner_id is not None:
            if action_type is ActionType.SOCIALIZE:
                bonus += 10.0
            elif action_type is ActionType.COURT:
                bonus += 12.0
        elif hint.kind is PlannerHintKind.PRIORITIZE_FOOD_SECURITY:
            if action_type is ActionType.GATHER_FOOD:
                bonus += 12.0
            elif action_type is ActionType.FETCH_WATER:
                bonus += 8.0
            elif action_type is ActionType.WORK_FIELD:
                bonus += 9.0
            elif action_type is ActionType.COOK:
                bonus += 6.0
            elif action_type is ActionType.EAT:
                bonus += 4.0
        elif hint.kind is PlannerHintKind.FOCUS_ON_RECOVERY:
            if action_type is ActionType.REST:
                bonus += 12.0
            elif action_type is ActionType.DRINK:
                bonus += 7.0
            elif action_type is ActionType.EAT:
                bonus += 6.0
            elif action_type is ActionType.FETCH_WATER:
                bonus += 4.0
        elif hint.kind is PlannerHintKind.IMPROVE_SOCIAL_STANDING:
            if action_type is ActionType.SOCIALIZE:
                bonus += 8.0
            elif action_type is ActionType.COURT:
                bonus += 5.0
        elif hint.kind is PlannerHintKind.CARE_FOR_CHILD_MORE and action_type is ActionType.CARE_FOR_CHILD:
            bonus += 14.0
        elif hint.kind is PlannerHintKind.PREPARE_FOR_WINTER:
            if action_type is ActionType.WORK_FIELD:
                bonus += 10.0
            elif action_type is ActionType.GATHER_FOOD:
                bonus += 8.0
            elif action_type is ActionType.COOK:
                bonus += 6.0
        elif hint.kind is PlannerHintKind.REDUCE_CONFLICT:
            if action_type is ActionType.SOCIALIZE:
                bonus -= 8.0
            elif action_type is ActionType.COURT:
                bonus -= 10.0
            elif action_type is ActionType.WANDER:
                bonus += 3.0
        elif hint.kind is PlannerHintKind.STAY_CLOSE_TO_HOME:
            if action_type is ActionType.REST:
                bonus += 4.0
            elif action_type is ActionType.COOK:
                bonus += 3.0
            elif action_type is ActionType.WANDER:
                bonus -= 4.0
        elif hint.kind is PlannerHintKind.AVOID_AGENT and hint.target_agent_id in visible_agents:
            if action_type is ActionType.SOCIALIZE:
                bonus -= 16.0
            elif action_type is ActionType.COURT:
                bonus -= 18.0
            elif action_type is ActionType.WANDER:
                bonus += 4.0
            elif action_type is ActionType.REST:
                bonus += 2.0
    return bonus


def _hint_matches_action(hint: PlannerHint, *, selected_action: str, visible_agents: set[str]) -> bool:
    if hint.kind is PlannerHintKind.VISIT_PARTNER:
        return selected_action in {"socialize", "court"}
    if hint.kind is PlannerHintKind.KEEP_ROUTINE:
        return selected_action == "idle"
    if hint.kind is PlannerHintKind.PRIORITIZE_FOOD_SECURITY:
        return selected_action in {"eat", "gather_food", "fetch_water", "work_field", "cook"}
    if hint.kind is PlannerHintKind.FOCUS_ON_RECOVERY:
        return selected_action in {"eat", "drink", "rest", "fetch_water"}
    if hint.kind is PlannerHintKind.GATHER_RESOURCES:
        return selected_action in {"gather_food", "fetch_water", "work_field"}
    if hint.kind is PlannerHintKind.EAT_SOON:
        return selected_action == "eat"
    if hint.kind is PlannerHintKind.DRINK_SOON:
        return selected_action == "drink"
    if hint.kind is PlannerHintKind.REST_SOON:
        return selected_action == "rest"
    if hint.kind is PlannerHintKind.REFLECT_ON_FAILURES:
        return selected_action == "wander"
    if hint.kind is PlannerHintKind.IMPROVE_SOCIAL_STANDING:
        return selected_action in {"socialize", "court"}
    if hint.kind is PlannerHintKind.CARE_FOR_CHILD_MORE:
        return selected_action == "care_for_child"
    if hint.kind is PlannerHintKind.REDUCE_CONFLICT:
        return selected_action in {"wander", "flee", "rest"}
    if hint.kind is PlannerHintKind.PREPARE_FOR_WINTER:
        return selected_action in {"gather_food", "work_field", "cook"}
    if hint.kind is PlannerHintKind.STAY_CLOSE_TO_HOME:
        return selected_action in {"rest", "cook"}
    if hint.kind is PlannerHintKind.AVOID_AGENT:
        return hint.target_agent_id in visible_agents and selected_action in {"wander", "flee", "rest"}
    return False


def _resolve_agent_reference(reference: str, world: WorldState) -> str | None:
    if world.agent_by_id(reference) is not None:
        return reference
    slug_reference = _slugify(reference)
    for candidate in world.agents:
        if _slugify(candidate.name) == slug_reference or _slugify(candidate.agent_id) == slug_reference:
            return candidate.agent_id
    return None


def _slugify(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.strip().lower()).strip("_")
