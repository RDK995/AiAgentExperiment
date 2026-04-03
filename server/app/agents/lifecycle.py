"""Deterministic lifecycle progression for authoritative agents."""

from __future__ import annotations

from datetime import datetime

from app.db.enums import AgentSex, StageOfLife
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent


class LifecycleService:
    """Advance aging, health, fertility, pregnancy, birth, and death state."""

    def __init__(self, gestation_ticks: int = 3) -> None:
        self._gestation_ticks = gestation_ticks

    def update(self, world: WorldState, tick: int, now: datetime, event_bus: EventBus) -> list[SimulationEvent]:
        """Advance lifecycle state for all living agents in the authoritative world."""

        events: list[SimulationEvent] = []
        for agent in list(world.agents):
            if not agent.alive:
                continue
            agent.age_ticks += 1
            previous_stage = agent.stage_of_life
            agent.stage_of_life = self._stage_for_age(agent.age_ticks)
            if agent.stage_of_life is not previous_stage:
                events.append(
                    self._emit(
                        event_bus,
                        EventType.MAJOR_LIFE_EVENT,
                        tick,
                        now,
                        agent.agent_id,
                        {"kind": "stage_progression", "stage_of_life": agent.stage_of_life.value},
                    )
                )

            if agent.hunger >= 95.0 or agent.thirst >= 95.0 or agent.fatigue >= 95.0:
                agent.health = max(0.0, agent.health - 2.0)

            if agent.pregnancy_progress_ticks is not None:
                agent.pregnancy_progress_ticks += 1
                if agent.pregnancy_progress_ticks >= self._gestation_ticks:
                    child = self._create_child(world, agent)
                    world.agents.append(child)
                    agent.pregnancy_progress_ticks = None
                    agent.pregnancy_partner_id = None
                    events.append(
                        self._emit(
                            event_bus,
                            EventType.BIRTH,
                            tick,
                            now,
                            agent.agent_id,
                            {"child_id": child.agent_id},
                        )
                    )

            if agent.health <= 0.0:
                agent.alive = False
                agent.current_action = "dead"
                events.append(
                    self._emit(
                        event_bus,
                        EventType.DEATH,
                        tick,
                        now,
                        agent.agent_id,
                        {"kind": "health_failure"},
                    )
                )
        return events

    @staticmethod
    def is_fertile(agent: AgentState) -> bool:
        """Return whether the current agent can enter pregnancy in the prototype rules."""

        return (
            agent.alive
            and agent.stage_of_life is StageOfLife.ADULT
            and agent.health >= 40.0
            and agent.sex in {AgentSex.FEMALE, AgentSex.INTERSEX}
            and agent.pregnancy_progress_ticks is None
        )

    def start_pregnancy(self, agent: AgentState, partner_id: str | None = None) -> None:
        """Begin a prototype pregnancy for a fertile agent."""

        if not self.is_fertile(agent):
            raise ValueError("Agent is not fertile.")
        agent.pregnancy_progress_ticks = 0
        agent.pregnancy_partner_id = partner_id

    @staticmethod
    def _stage_for_age(age_ticks: int) -> StageOfLife:
        """Map the prototype age counter into a stage of life."""

        if age_ticks < 100:
            return StageOfLife.INFANT
        if age_ticks < 500:
            return StageOfLife.CHILD
        if age_ticks < 1_000:
            return StageOfLife.ADOLESCENT
        if age_ticks < 10_000:
            return StageOfLife.ADULT
        return StageOfLife.ELDER

    @staticmethod
    def _create_child(world: WorldState, parent: AgentState) -> AgentState:
        """Create a deterministic infant agent next to the parent."""

        return AgentState(
            agent_id=world.next_agent_id(),
            name=f"Child {len(world.agents) + 1}",
            x=parent.x,
            y=parent.y,
            sex=AgentSex.INTERSEX,
            stage_of_life=StageOfLife.INFANT,
            age_ticks=0,
            household_id=parent.household_id,
            partner_id=None,
        )

    @staticmethod
    def _emit(
        event_bus: EventBus,
        event_type: EventType,
        tick: int,
        now: datetime,
        agent_id: str,
        payload: dict[str, object],
    ) -> SimulationEvent:
        """Create and enqueue a lifecycle event."""

        event = SimulationEvent(
            type=event_type,
            tick=tick,
            sim_time=now,
            agent_id=agent_id,
            payload=payload,
        )
        event_bus.emit(event)
        return event
