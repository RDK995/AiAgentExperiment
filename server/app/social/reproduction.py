"""Deterministic reproduction helpers built on authoritative lifecycle state."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
import uuid

from sqlalchemy.orm import Session

from app.db.enums import AgentSex, GoalSource, GoalStatus, GoalType, KinshipType, PregnancyStatus, StageOfLife
from app.db.repositories import (
    AgentCreateParams,
    AgentRepository,
    GoalCreateParams,
    PregnancyCreateParams,
    RelationshipCreateParams,
)
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent
from app.social.bonding import RelationshipMetrics
from app.social.inheritance import TraitInheritanceService


@dataclass(slots=True)
class PregnancyAttemptResult:
    """Outcome of one conception attempt."""

    started: bool
    probability: float
    reason: str | None = None
    event: SimulationEvent | None = None


class ReproductionService:
    """Handle conception, birth, and persistence-aware family state updates."""

    def __init__(
        self,
        *,
        gestation_ticks: int = 3,
        random_fn: Callable[[], float] | None = None,
        session_scope: Callable[[], AbstractContextManager[Session]] | None = None,
        resolve_agent_id: Callable[[str], uuid.UUID | None] | None = None,
        register_agent_id: Callable[[str, uuid.UUID], None] | None = None,
        inheritance_service: TraitInheritanceService | None = None,
    ) -> None:
        self._gestation_ticks = gestation_ticks
        self._random_fn = random_fn or (lambda: 1.0)
        self._session_scope = session_scope
        self._resolve_agent_id = resolve_agent_id
        self._register_agent_id = register_agent_id
        self._inheritance = inheritance_service or TraitInheritanceService()

    def compute_conception_probability(
        self,
        mother: AgentState,
        father: AgentState,
        relationship: RelationshipMetrics | None = None,
    ) -> float:
        """Compute an explicit bounded conception probability for a bonded pair."""

        relationship = relationship or RelationshipMetrics(
            familiarity=0.5,
            trust=0.5,
            attraction=0.5,
            admiration=0.5,
        )
        base = 0.08
        relationship_bonus = ((relationship.attraction + relationship.trust) / 2.0) * 0.18
        family_bonus = ((mother.family_orientation + father.family_orientation) / 2.0) * 0.18
        health_factor = max(0.0, min(1.0, mother.health / 100.0)) * 0.12
        probability = base + relationship_bonus + family_bonus + health_factor
        return max(0.0, min(0.75, round(probability, 4)))

    def try_conception(
        self,
        world: WorldState,
        mother: AgentState,
        father: AgentState,
        *,
        tick: int,
        now: datetime,
        event_bus: EventBus,
        is_fertile: Callable[[AgentState], bool],
        start_pregnancy: Callable[..., SimulationEvent | None],
        relationship: RelationshipMetrics | None = None,
    ) -> PregnancyAttemptResult:
        """Attempt conception for a bonded pair without bypassing lifecycle rules."""

        if mother.partner_id != father.agent_id or father.partner_id != mother.agent_id:
            return PregnancyAttemptResult(False, 0.0, reason="not_bonded")
        if mother.pregnancy_progress_ticks is not None:
            return PregnancyAttemptResult(False, 0.0, reason="already_pregnant")
        if not mother.alive or not father.alive:
            return PregnancyAttemptResult(False, 0.0, reason="dead_partner")
        if mother.stage_of_life is not StageOfLife.ADULT or father.stage_of_life is not StageOfLife.ADULT:
            return PregnancyAttemptResult(False, 0.0, reason="not_adults")
        if not is_fertile(mother):
            return PregnancyAttemptResult(False, 0.0, reason="mother_not_fertile")
        if self._has_active_persistent_pregnancy(mother.agent_id):
            return PregnancyAttemptResult(False, 0.0, reason="duplicate_persistent_pregnancy")

        probability = self.compute_conception_probability(mother, father, relationship=relationship)
        if self._random_fn() >= probability:
            return PregnancyAttemptResult(False, probability, reason="conception_missed")

        event = start_pregnancy(
            mother,
            father.agent_id,
            tick=tick,
            now=now,
            event_bus=event_bus,
        )
        mother.hunger = min(100.0, mother.hunger + 4.0)
        mother.fatigue = min(100.0, mother.fatigue + 5.0)
        mother.health = max(0.0, mother.health - 2.0)
        mother.household_planning_pressure = min(100.0, mother.household_planning_pressure + 20.0)
        father.household_planning_pressure = min(100.0, father.household_planning_pressure + 10.0)
        self._persist_pregnancy(mother.agent_id, father.agent_id, tick=tick)
        return PregnancyAttemptResult(True, probability, event=event)

    def handle_birth(
        self,
        world: WorldState,
        mother: AgentState,
        father: AgentState | None,
        *,
        tick: int,
        now: datetime,
        event_bus: EventBus,
    ) -> tuple[AgentState, list[SimulationEvent]]:
        """Create an infant, seed parent obligations, and emit birth events."""

        child = self._create_child(world, mother, father)
        mother.has_infant_care_duty = True
        mother.household_planning_pressure = min(100.0, mother.household_planning_pressure + 15.0)
        if father is not None:
            father.has_infant_care_duty = True
            father.household_planning_pressure = min(100.0, father.household_planning_pressure + 10.0)

        if mother.current_goal == "Maintain daily routine":
            mother.current_goal = f"Care for {child.name}"
        if father is not None and father.current_goal == "Maintain daily routine":
            father.current_goal = f"Care for {child.name}"

        self._persist_birth(child, mother=mother, father=father, tick=tick)

        actor_ids = [mother.agent_id]
        if father is not None:
            actor_ids.append(father.agent_id)
        payload = {
            "child_id": child.agent_id,
            "household_id": child.household_id,
            "parent_ids": list(child.parent_ids),
        }
        birth_event = self._emit_birth_event(
            event_bus,
            event_type=EventType.BIRTH,
            tick=tick,
            now=now,
            location_agent=mother,
            actor_ids=actor_ids,
            child=child,
            payload=payload,
        )
        child_born_event = self._emit_birth_event(
            event_bus,
            event_type=EventType.CHILD_BORN,
            tick=tick,
            now=now,
            location_agent=mother,
            actor_ids=actor_ids,
            child=child,
            payload=payload,
        )
        return child, [birth_event, child_born_event]

    def _create_child(self, world: WorldState, mother: AgentState, father: AgentState | None) -> AgentState:
        family_orientation = self._inheritance.inherit_runtime_family_orientation(
            mother.family_orientation,
            father.family_orientation if father is not None else mother.family_orientation,
        )
        household_id = mother.household_id or (father.household_id if father is not None else f"household-{mother.agent_id}")
        parent_ids = [mother.agent_id]
        if father is not None:
            parent_ids.append(father.agent_id)
        return AgentState(
            agent_id=world.next_agent_id(),
            name=f"Child {len(world.agents) + 1}",
            x=mother.x,
            y=mother.y,
            sex=AgentSex.INTERSEX,
            stage_of_life=StageOfLife.INFANT,
            age_ticks=0,
            household_id=household_id,
            partner_id=None,
            parent_ids=parent_ids,
            family_orientation=family_orientation,
        )

    @staticmethod
    def _emit_birth_event(
        event_bus: EventBus,
        *,
        event_type: EventType,
        tick: int,
        now: datetime,
        location_agent: AgentState,
        actor_ids: list[str],
        child: AgentState,
        payload: dict[str, object],
    ) -> SimulationEvent:
        event = SimulationEvent(
            type=event_type,
            tick=tick,
            sim_time=now,
            agent_id=actor_ids[0] if actor_ids else None,
            actor_ids=list(actor_ids),
            target_ids=[child.agent_id],
            location_x=location_agent.x,
            location_y=location_agent.y,
            source_module="reproduction",
            payload=payload,
        )
        event_bus.emit(event)
        return event

    def _has_active_persistent_pregnancy(self, mother_agent_id: str) -> bool:
        if self._session_scope is None or self._resolve_agent_id is None:
            return False
        mother_uuid = self._resolve_agent_id(mother_agent_id)
        if mother_uuid is None:
            return False
        with self._session_scope() as session:
            repository = AgentRepository(session)
            return repository.get_active_pregnancy(mother_uuid) is not None

    def _persist_pregnancy(self, mother_agent_id: str, father_agent_id: str | None, *, tick: int) -> None:
        if self._session_scope is None or self._resolve_agent_id is None:
            return
        mother_uuid = self._resolve_agent_id(mother_agent_id)
        if mother_uuid is None:
            return
        father_uuid = self._resolve_agent_id(father_agent_id) if father_agent_id is not None else None

        with self._session_scope() as session:
            repository = AgentRepository(session)
            mother = repository.get_agent_with_related(mother_uuid)
            if mother is None:
                return
            if repository.get_active_pregnancy(mother_uuid) is not None:
                return
            repository.create_pregnancy(
                PregnancyCreateParams(
                    mother_id=mother_uuid,
                    father_id=father_uuid,
                    started_tick=tick,
                    expected_birth_tick=tick + self._gestation_ticks,
                    status=PregnancyStatus.ACTIVE,
                )
            )
            mother.needs.hunger = min(100.0, mother.needs.hunger + 4.0)
            mother.needs.fatigue = min(100.0, mother.needs.fatigue + 5.0)
            mother.needs.health = max(0.0, mother.needs.health - 2.0)
            session.flush()

    def _persist_birth(self, child: AgentState, *, mother: AgentState, father: AgentState | None, tick: int) -> None:
        if self._session_scope is None or self._resolve_agent_id is None:
            return
        mother_uuid = self._resolve_agent_id(mother.agent_id)
        if mother_uuid is None:
            return
        father_uuid = self._resolve_agent_id(father.agent_id) if father is not None else None

        with self._session_scope() as session:
            repository = AgentRepository(session)
            persistent_mother = repository.get_agent_with_related(mother_uuid)
            if persistent_mother is None:
                return
            persistent_father = repository.get_agent_with_related(father_uuid) if father_uuid is not None else None

            inherited_traits = self._inheritance.inherit_persistent_traits(
                _trait_dict_for_agent(persistent_mother),
                _trait_dict_for_agent(persistent_father),
            )
            persistent_child = repository.create_agent_bundle(
                AgentCreateParams(
                    name=child.name,
                    sex=child.sex,
                    birth_tick=tick,
                    current_tile_x=child.x,
                    current_tile_y=child.y,
                    stage_of_life=StageOfLife.INFANT,
                    household_id=_coalesce_household_id(persistent_mother, persistent_father),
                    trait_values=inherited_traits,
                    biography_summary=f"{child.name} was born into the village.",
                )
            )
            if self._register_agent_id is not None:
                self._register_agent_id(child.agent_id, persistent_child.id)

            self._link_parent_child(repository, parent_id=persistent_mother.id, child_id=persistent_child.id, tick=tick)
            if persistent_father is not None:
                self._link_parent_child(repository, parent_id=persistent_father.id, child_id=persistent_child.id, tick=tick)

            self._seed_parent_goals(repository, persistent_mother.id, child_name=child.name, tick=tick)
            if persistent_father is not None:
                self._seed_parent_goals(repository, persistent_father.id, child_name=child.name, tick=tick)

            active_pregnancy = repository.get_active_pregnancy(persistent_mother.id)
            if active_pregnancy is not None:
                active_pregnancy.status = PregnancyStatus.BIRTH
            session.flush()

    @staticmethod
    def _link_parent_child(repository: AgentRepository, *, parent_id: uuid.UUID, child_id: uuid.UUID, tick: int) -> None:
        if repository.get_relationship(parent_id, child_id) is None:
            repository.create_relationship(
                RelationshipCreateParams(
                    source_agent_id=parent_id,
                    target_agent_id=child_id,
                    familiarity=1.0,
                    trust=0.9,
                    admiration=0.4,
                    kinship_type=KinshipType.PARENT,
                    last_interaction_tick=tick,
                )
            )
        if repository.get_relationship(child_id, parent_id) is None:
            repository.create_relationship(
                RelationshipCreateParams(
                    source_agent_id=child_id,
                    target_agent_id=parent_id,
                    familiarity=1.0,
                    trust=0.9,
                    admiration=0.2,
                    dependency=1.0,
                    kinship_type=KinshipType.CHILD,
                    last_interaction_tick=tick,
                )
            )

    @staticmethod
    def _seed_parent_goals(repository: AgentRepository, parent_id: uuid.UUID, *, child_name: str, tick: int) -> None:
        existing_titles = {goal.title for goal in repository.list_goals_for_agent(parent_id, status=GoalStatus.ACTIVE)}
        desired_goals = [
            (GoalType.FAMILY, f"Care for {child_name}", 0.95, 3),
            (GoalType.SAFETY, "Increase household food security", 0.9, 5),
        ]
        for goal_type, title, priority, horizon_days in desired_goals:
            if title in existing_titles:
                continue
            repository.create_goal(
                GoalCreateParams(
                    agent_id=parent_id,
                    goal_type=goal_type,
                    title=title,
                    priority=priority,
                    horizon_days=horizon_days,
                    status=GoalStatus.ACTIVE,
                    source=GoalSource.INHERITED,
                    created_tick=tick,
                    updated_tick=tick,
                )
            )


def _trait_dict_for_agent(agent) -> dict[str, float] | None:
    if agent is None or getattr(agent, "traits", None) is None:
        return None
    traits = agent.traits
    return {
        "sociability": traits.sociability,
        "aggression": traits.aggression,
        "conscientiousness": traits.conscientiousness,
        "curiosity": traits.curiosity,
        "family_orientation": traits.family_orientation,
        "risk_tolerance": traits.risk_tolerance,
        "libido": traits.libido,
        "emotional_stability": traits.emotional_stability,
        "memory_fidelity": traits.memory_fidelity,
        "learning_rate": traits.learning_rate,
    }


def _coalesce_household_id(mother, father) -> uuid.UUID | None:
    if mother is not None and mother.household_id is not None:
        return mother.household_id
    if father is not None and father.household_id is not None:
        return father.household_id
    if mother is not None:
        return mother.id
    if father is not None:
        return father.id
    return None
