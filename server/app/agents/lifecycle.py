"""Deterministic lifecycle progression for authoritative agents."""

from __future__ import annotations

from datetime import datetime

from app.db.enums import AgentSex, StageOfLife
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent
from app.social.bonding import BondingService
from app.social.bonding import RelationshipMetrics
from app.social.reproduction import ReproductionService


class LifecycleService:
    """Advance aging, health, fertility, pregnancy, birth, and death state."""

    def __init__(
        self,
        gestation_ticks: int = 3,
        reproduction_service: ReproductionService | None = None,
        bonding_service: BondingService | None = None,
    ) -> None:
        self._gestation_ticks = gestation_ticks
        self._reproduction_service = reproduction_service
        self._bonding_service = bonding_service

    def update(self, world: WorldState, tick: int, now: datetime, event_bus: EventBus) -> list[SimulationEvent]:
        """Advance lifecycle state for all living agents in the authoritative world."""

        events: list[SimulationEvent] = []
        if self._bonding_service is not None:
            events.extend(
                self._bonding_service.evaluate_social_opportunities(
                    world,
                    tick=tick,
                    now=now,
                    event_bus=event_bus,
                )
            )
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
                        agent,
                        {"kind": "stage_progression", "stage_of_life": agent.stage_of_life.value},
                    )
                )

            if agent.hunger >= 95.0 or agent.thirst >= 95.0 or agent.fatigue >= 95.0:
                agent.health = max(0.0, agent.health - 2.0)

            if (
                self._reproduction_service is not None
                and agent.pregnancy_progress_ticks is None
                and agent.partner_id is not None
            ):
                partner = world.agent_by_id(agent.partner_id)
                if partner is not None:
                    conception = self._reproduction_service.try_conception(
                        world,
                        agent,
                        partner,
                        tick=tick,
                        now=now,
                        event_bus=event_bus,
                        is_fertile=self.is_fertile,
                        start_pregnancy=self.start_pregnancy,
                        relationship=RelationshipMetrics(
                            familiarity=1.0 if partner.partner_id == agent.agent_id else 0.6,
                            trust=0.7,
                            attraction=0.7,
                            admiration=0.5,
                        ),
                    )
                    if conception.event is not None:
                        events.append(conception.event)

            if agent.pregnancy_progress_ticks is not None:
                agent.pregnancy_progress_ticks += 1
                if agent.pregnancy_progress_ticks >= self._gestation_ticks:
                    father = world.agent_by_id(agent.pregnancy_partner_id) if agent.pregnancy_partner_id is not None else None
                    if self._reproduction_service is not None:
                        child, birth_events = self._reproduction_service.handle_birth(
                            world,
                            agent,
                            father,
                            tick=tick,
                            now=now,
                            event_bus=event_bus,
                        )
                    else:
                        child = self._create_child(world, agent)
                        birth_events = [
                            self._emit(
                                event_bus,
                                EventType.BIRTH,
                                tick,
                                now,
                                agent,
                                {"child_id": child.agent_id},
                                target_ids=[child.agent_id],
                            ),
                            self._emit(
                                event_bus,
                                EventType.CHILD_BORN,
                                tick,
                                now,
                                agent,
                                {"child_id": child.agent_id},
                                target_ids=[child.agent_id],
                            ),
                        ]
                    world.agents.append(child)
                    agent.pregnancy_progress_ticks = None
                    agent.pregnancy_partner_id = None
                    events.extend(birth_events)

            if agent.health <= 0.0:
                agent.alive = False
                agent.current_action = "dead"
                events.append(
                    self._emit(
                        event_bus,
                        EventType.DEATH,
                        tick,
                        now,
                        agent,
                        {"kind": "health_failure"},
                    )
                )
                events.append(
                    self._emit(
                        event_bus,
                        EventType.AGENT_DIED,
                        tick,
                        now,
                        agent,
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

    def start_pregnancy(
        self,
        agent: AgentState,
        partner_id: str | None = None,
        *,
        tick: int | None = None,
        now: datetime | None = None,
        event_bus: EventBus | None = None,
    ) -> SimulationEvent | None:
        """Begin a prototype pregnancy for a fertile agent."""

        if not self.is_fertile(agent):
            raise ValueError("Agent is not fertile.")
        agent.pregnancy_progress_ticks = 0
        agent.pregnancy_partner_id = partner_id
        if event_bus is not None and tick is not None and now is not None:
            return self._emit(
                event_bus,
                EventType.PREGNANCY_STARTED,
                tick,
                now,
                agent,
                {"partner_id": partner_id} if partner_id is not None else {},
                target_ids=[partner_id] if partner_id is not None else [],
            )
        return None

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
            parent_ids=[parent.agent_id],
            family_orientation=parent.family_orientation,
        )

    @staticmethod
    def _emit(
        event_bus: EventBus,
        event_type: EventType,
        tick: int,
        now: datetime,
        agent: AgentState,
        payload: dict[str, object],
        *,
        target_ids: list[str] | None = None,
    ) -> SimulationEvent:
        """Create and enqueue a lifecycle event."""

        event = SimulationEvent(
            type=event_type,
            tick=tick,
            sim_time=now,
            agent_id=agent.agent_id,
            actor_ids=[agent.agent_id],
            target_ids=list(target_ids or []),
            location_x=agent.x,
            location_y=agent.y,
            source_module="lifecycle",
            payload=payload,
        )
        event_bus.emit(event)
        return event
