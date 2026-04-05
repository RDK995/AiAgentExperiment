"""Deterministic reflection trigger evaluation helpers."""

from __future__ import annotations

from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent


class ReflectionTriggerEvaluator:
    """Evaluate event-driven and state-driven triggers for the slow loop."""

    def __init__(
        self,
        *,
        severe_hunger_threshold: float = 90.0,
        severe_health_threshold: float = 25.0,
    ) -> None:
        self._severe_hunger_threshold = severe_hunger_threshold
        self._severe_health_threshold = severe_health_threshold

    def apply_event_trigger(self, world: WorldState, event: SimulationEvent) -> None:
        """Apply trigger flags for one authoritative event."""

        if event.type is EventType.DAY_ROLLOVER:
            next_day_index = event.payload.get("day_index")
            for agent in world.agents:
                if next_day_index is not None and agent.daily_summary_day_index != next_day_index:
                    agent.daily_summary_day_index = next_day_index
                    agent.daily_summary_candidates = []
                agent.slow_loop_trigger_flags.add("day_rollover")
            return

        if event.type is EventType.PLAN_FAILED:
            self._apply_plan_failure_trigger(world, event)
            return

        if event.type in {EventType.BIRTH, EventType.CHILD_BORN}:
            self._apply_birth_trigger(world, event)
            return

        if event.type in {EventType.DEATH, EventType.AGENT_DIED}:
            self._apply_death_trigger(world, event)
            return

        if event.type is EventType.PROPOSAL_ACCEPTED or (
            event.type is EventType.PROPOSAL_MADE and event.payload.get("outcome") == "rejected"
        ):
            self._apply_actor_target_trigger(world, event, "bond_proposal_decision")
            return

        if event.type is EventType.GIFT_GIVEN and (
            event.payload.get("major_gift") or event.payload.get("target_was_starving")
        ):
            self._apply_actor_target_trigger(world, event, "major_gift")
            return

        if event.type is EventType.INSULT_SPOKEN and (
            event.payload.get("betrayal") or event.payload.get("public")
        ):
            self._apply_actor_target_trigger(world, event, "betrayal")
            return

        if event.type is EventType.MAJOR_LIFE_EVENT:
            self._apply_actor_target_trigger(world, event, "major_life_event")
            return

        if event.type is EventType.SOCIAL_MILESTONE:
            self._apply_actor_target_trigger(world, event, "social_milestone")

    def apply_state_triggers(self, world: WorldState) -> None:
        """Apply deterministic state-based triggers not tied to one event."""

        for agent in world.agents:
            if not agent.alive:
                continue
            if agent.hunger >= self._severe_hunger_threshold or agent.health <= self._severe_health_threshold:
                agent.slow_loop_trigger_flags.add("severe_hunger_or_injury")

    @staticmethod
    def _apply_actor_target_trigger(world: WorldState, event: SimulationEvent, reason: str) -> None:
        agent_ids = set(event.actor_ids) | set(event.target_ids)
        if event.agent_id is not None:
            agent_ids.add(event.agent_id)
        for agent_id in agent_ids:
            agent = world.agent_by_id(agent_id)
            if agent is not None:
                agent.slow_loop_trigger_flags.add(reason)

    @staticmethod
    def _apply_plan_failure_trigger(world: WorldState, event: SimulationEvent) -> None:
        target_agent = world.agent_by_id(event.agent_id) if event.agent_id is not None else None
        if target_agent is not None and target_agent.plan_failure_count >= 3:
            target_agent.slow_loop_trigger_flags.add("repeated_plan_failure")

    def _apply_birth_trigger(self, world: WorldState, event: SimulationEvent) -> None:
        parent = world.agent_by_id(event.agent_id) if event.agent_id is not None else None
        if parent is None:
            self._apply_actor_target_trigger(world, event, "birth_in_household")
            return
        for agent in world.agents:
            if agent.agent_id == parent.agent_id:
                agent.slow_loop_trigger_flags.add("birth_in_household")
            elif parent.household_id is not None and agent.household_id == parent.household_id:
                agent.slow_loop_trigger_flags.add("birth_in_household")
            elif agent.partner_id == parent.agent_id or parent.partner_id == agent.agent_id:
                agent.slow_loop_trigger_flags.add("birth_in_household")

    def _apply_death_trigger(self, world: WorldState, event: SimulationEvent) -> None:
        deceased = world.agent_by_id(event.agent_id) if event.agent_id is not None else None
        if deceased is None:
            self._apply_actor_target_trigger(world, event, "death_of_close_relation")
            return
        for agent in world.agents:
            if agent.agent_id == deceased.agent_id:
                continue
            if self._is_close_relation(agent, deceased):
                agent.slow_loop_trigger_flags.add("death_of_close_relation")

    @staticmethod
    def _is_close_relation(agent: AgentState, other: AgentState) -> bool:
        return (
            agent.partner_id == other.agent_id
            or other.partner_id == agent.agent_id
            or (
                agent.household_id is not None
                and other.household_id is not None
                and agent.household_id == other.household_id
            )
        )
