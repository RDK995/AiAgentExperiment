"""Deterministic pair-bond eligibility and scoring helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
import uuid

from app.db.enums import PairBondState, StageOfLife
from app.db.repositories import AgentRepository, PairBondCreateParams
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent


@dataclass(slots=True, frozen=True)
class RelationshipMetrics:
    """Compact relationship metrics used for bonding decisions."""

    familiarity: float
    trust: float
    attraction: float
    admiration: float = 0.0


@dataclass(slots=True)
class BondAttemptResult:
    """Outcome for one bond attempt."""

    attempted: bool
    accepted: bool
    bond_score: float
    reciprocal_score: float
    reason: str | None = None
    events: list[SimulationEvent] | None = None


class BondingService:
    """Evaluate eligibility, score attraction, and form pair bonds safely."""

    def __init__(
        self,
        *,
        attraction_threshold: float = 0.45,
        trust_threshold: float = 0.40,
        familiarity_threshold: float = 0.35,
        acceptance_threshold: float = 0.60,
        rejection_cooldown_ticks: int = 6,
        session_factory: Callable | None = None,
        resolve_agent_id: Callable[[str], uuid.UUID | None] | None = None,
    ) -> None:
        self._attraction_threshold = attraction_threshold
        self._trust_threshold = trust_threshold
        self._familiarity_threshold = familiarity_threshold
        self._acceptance_threshold = acceptance_threshold
        self._rejection_cooldown_ticks = rejection_cooldown_ticks
        self._session_factory = session_factory
        self._resolve_agent_id = resolve_agent_id

    def can_attempt_bond(
        self,
        agent_a: AgentState,
        agent_b: AgentState,
        relationship: RelationshipMetrics | None,
        *,
        world: WorldState,
        tick: int,
    ) -> bool:
        """Return whether one agent may attempt a bond with another."""

        if relationship is None:
            return False
        if agent_a.agent_id == agent_b.agent_id:
            return False
        if not agent_a.alive or not agent_b.alive:
            return False
        if agent_a.stage_of_life is not StageOfLife.ADULT or agent_b.stage_of_life is not StageOfLife.ADULT:
            return False
        if agent_a.partner_id == agent_b.agent_id and agent_b.partner_id == agent_a.agent_id:
            return False
        if agent_a.bond_rejection_until_tick is not None and tick < agent_a.bond_rejection_until_tick:
            return False
        if agent_b.bond_rejection_until_tick is not None and tick < agent_b.bond_rejection_until_tick:
            return False
        if agent_a.partner_id not in {None, agent_b.agent_id}:
            return False
        if agent_b.partner_id not in {None, agent_a.agent_id}:
            return False
        if relationship.attraction < self._attraction_threshold:
            return False
        if relationship.trust < self._trust_threshold:
            return False
        if relationship.familiarity < self._familiarity_threshold:
            return False
        return self._has_social_opportunity(agent_a, agent_b, world)

    def compute_availability_bonus(self, agent_a: AgentState, agent_b: AgentState, world: WorldState) -> float:
        """Score whether a pair is logistically available for pair bonding."""

        distance = abs(agent_a.x - agent_b.x) + abs(agent_a.y - agent_b.y)
        same_household = (
            agent_a.household_id is not None
            and agent_b.household_id is not None
            and agent_a.household_id == agent_b.household_id
        )
        if same_household:
            return 1.0
        if distance <= 1:
            return 0.8
        if distance <= 2:
            return 0.5
        return 0.0

    def compute_bond_score(
        self,
        relationship: RelationshipMetrics,
        *,
        family_orientation: float,
        availability_bonus: float,
    ) -> float:
        """Compute a bounded bond score from relationship and family traits."""

        score = (
            relationship.attraction * 0.35
            + relationship.trust * 0.25
            + relationship.admiration * 0.10
            + family_orientation * 0.15
            + availability_bonus * 0.15
        )
        return max(0.0, min(1.0, round(score, 4)))

    def attempt_bond(
        self,
        agent_a: AgentState,
        agent_b: AgentState,
        relationship_ab: RelationshipMetrics | None,
        relationship_ba: RelationshipMetrics | None,
        *,
        world: WorldState,
        tick: int,
        now: datetime,
        event_bus: EventBus,
    ) -> BondAttemptResult:
        """Attempt a bond proposal and either accept it or apply rejection cooldown."""

        if not self.can_attempt_bond(agent_a, agent_b, relationship_ab, world=world, tick=tick):
            return BondAttemptResult(False, False, 0.0, 0.0, reason="ineligible", events=[])

        availability_bonus = self.compute_availability_bonus(agent_a, agent_b, world)
        proposal_event = self._emit(
            event_bus,
            event_type=EventType.PROPOSAL_MADE,
            tick=tick,
            now=now,
            actor=agent_a,
            target=agent_b,
            payload={"bond_score": self.compute_bond_score(
                relationship_ab,
                family_orientation=agent_a.family_orientation,
                availability_bonus=availability_bonus,
            )},
        )

        if relationship_ba is None:
            agent_a.bond_rejection_until_tick = tick + self._rejection_cooldown_ticks
            return BondAttemptResult(
                True,
                False,
                proposal_event.payload["bond_score"],  # type: ignore[index]
                0.0,
                reason="missing_reciprocal_relationship",
                events=[proposal_event],
            )

        bond_score = self.compute_bond_score(
            relationship_ab,
            family_orientation=agent_a.family_orientation,
            availability_bonus=availability_bonus,
        )
        reciprocal_score = self.compute_bond_score(
            relationship_ba,
            family_orientation=agent_b.family_orientation,
            availability_bonus=availability_bonus,
        )

        if bond_score < self._acceptance_threshold or reciprocal_score < self._acceptance_threshold:
            agent_a.bond_rejection_until_tick = tick + self._rejection_cooldown_ticks
            return BondAttemptResult(
                True,
                False,
                bond_score,
                reciprocal_score,
                reason="proposal_rejected",
                events=[proposal_event],
            )

        agent_a.partner_id = agent_b.agent_id
        agent_b.partner_id = agent_a.agent_id
        agent_a.bond_rejection_until_tick = None
        agent_b.bond_rejection_until_tick = None
        accepted_event = self._emit(
            event_bus,
            event_type=EventType.PROPOSAL_ACCEPTED,
            tick=tick,
            now=now,
            actor=agent_a,
            target=agent_b,
            payload={"bond_score": bond_score, "reciprocal_score": reciprocal_score},
        )
        self._persist_pair_bond(agent_a.agent_id, agent_b.agent_id, tick=tick, bond_strength=(bond_score + reciprocal_score) / 2.0)
        return BondAttemptResult(
            True,
            True,
            bond_score,
            reciprocal_score,
            events=[proposal_event, accepted_event],
        )

    def evaluate_social_opportunities(
        self,
        world: WorldState,
        *,
        tick: int,
        now: datetime,
        event_bus: EventBus,
    ) -> list[SimulationEvent]:
        """Attempt deterministic pair-bond proposals for nearby eligible adults."""

        if self._session_factory is None or self._resolve_agent_id is None:
            return []

        agents = sorted(
            [agent for agent in world.agents if agent.alive and agent.stage_of_life is StageOfLife.ADULT],
            key=lambda candidate: candidate.agent_id,
        )
        events: list[SimulationEvent] = []
        engaged_ids: set[str] = set()

        for index, agent_a in enumerate(agents):
            if agent_a.agent_id in engaged_ids:
                continue
            best_candidate: tuple[float, AgentState, AgentState, RelationshipMetrics, RelationshipMetrics] | None = None
            for agent_b in agents[index + 1 :]:
                if agent_b.agent_id in engaged_ids:
                    continue
                if not self._has_social_opportunity(agent_a, agent_b, world):
                    continue
                relationship_ab = self._load_relationship_metrics(agent_a.agent_id, agent_b.agent_id)
                relationship_ba = self._load_relationship_metrics(agent_b.agent_id, agent_a.agent_id)
                if relationship_ab is None or relationship_ba is None:
                    continue
                if not self.can_attempt_bond(agent_a, agent_b, relationship_ab, world=world, tick=tick):
                    continue
                if not self.can_attempt_bond(agent_b, agent_a, relationship_ba, world=world, tick=tick):
                    continue

                availability_bonus = self.compute_availability_bonus(agent_a, agent_b, world)
                score_ab = self.compute_bond_score(
                    relationship_ab,
                    family_orientation=agent_a.family_orientation,
                    availability_bonus=availability_bonus,
                )
                score_ba = self.compute_bond_score(
                    relationship_ba,
                    family_orientation=agent_b.family_orientation,
                    availability_bonus=availability_bonus,
                )
                pair_score = max(score_ab, score_ba)
                ordered_relationships = (relationship_ab, relationship_ba)
                proposer, target = agent_a, agent_b
                if (score_ba, agent_b.agent_id) > (score_ab, agent_a.agent_id):
                    proposer, target = agent_b, agent_a
                    ordered_relationships = (relationship_ba, relationship_ab)

                candidate = (pair_score, proposer, target, ordered_relationships[0], ordered_relationships[1])
                if best_candidate is None or candidate[0] > best_candidate[0] or (
                    candidate[0] == best_candidate[0] and proposer.agent_id < best_candidate[1].agent_id
                ):
                    best_candidate = candidate

            if best_candidate is None:
                continue

            _, proposer, target, relationship_forward, relationship_reverse = best_candidate

            result = self.attempt_bond(
                proposer,
                target,
                relationship_forward,
                relationship_reverse,
                world=world,
                tick=tick,
                now=now,
                event_bus=event_bus,
            )
            engaged_ids.add(proposer.agent_id)
            engaged_ids.add(target.agent_id)
            events.extend(result.events or [])

        return events

    def get_relationship_metrics(self, source_agent_id: str, target_agent_id: str) -> RelationshipMetrics | None:
        """Load persisted relationship metrics for a directed pair when available."""

        return self._load_relationship_metrics(source_agent_id, target_agent_id)

    @staticmethod
    def _has_social_opportunity(agent_a: AgentState, agent_b: AgentState, world: WorldState) -> bool:
        distance = abs(agent_a.x - agent_b.x) + abs(agent_a.y - agent_b.y)
        same_household = (
            agent_a.household_id is not None
            and agent_b.household_id is not None
            and agent_a.household_id == agent_b.household_id
        )
        return same_household or distance <= 2

    @staticmethod
    def _emit(
        event_bus: EventBus,
        *,
        event_type: EventType,
        tick: int,
        now: datetime,
        actor: AgentState,
        target: AgentState,
        payload: dict[str, object],
    ) -> SimulationEvent:
        event = SimulationEvent(
            type=event_type,
            tick=tick,
            sim_time=now,
            agent_id=actor.agent_id,
            actor_ids=[actor.agent_id],
            target_ids=[target.agent_id],
            location_x=actor.x,
            location_y=actor.y,
            source_module="bonding",
            payload=payload,
        )
        event_bus.emit(event)
        return event

    def _persist_pair_bond(self, agent_a_id: str, agent_b_id: str, *, tick: int, bond_strength: float) -> None:
        if self._session_factory is None or self._resolve_agent_id is None:
            return

        with self._session_factory() as session:
            repository = AgentRepository(session)
            agent_a_uuid = self._resolve_agent_id(agent_a_id)
            agent_b_uuid = self._resolve_agent_id(agent_b_id)
            if agent_a_uuid is None or agent_b_uuid is None:
                return

            pair_bond = repository.get_pair_bond_between(agent_a_uuid, agent_b_uuid)
            if pair_bond is None:
                repository.create_pair_bond(
                    PairBondCreateParams(
                        agent_a_id=agent_a_uuid,
                        agent_b_id=agent_b_uuid,
                        state=PairBondState.BONDED,
                        bond_strength=bond_strength,
                        started_tick=tick,
                    )
                )
            else:
                pair_bond.state = PairBondState.BONDED
                pair_bond.bond_strength = max(pair_bond.bond_strength, bond_strength)
                pair_bond.ended_tick = None
                session.flush()

    def _load_relationship_metrics(self, source_agent_id: str, target_agent_id: str) -> RelationshipMetrics | None:
        if self._session_factory is None or self._resolve_agent_id is None:
            return None

        source_uuid = self._resolve_agent_id(source_agent_id)
        target_uuid = self._resolve_agent_id(target_agent_id)
        if source_uuid is None or target_uuid is None:
            return None

        with self._session_factory() as session:
            repository = AgentRepository(session)
            relationship = repository.get_relationship(source_uuid, target_uuid)
            if relationship is None:
                return None
            return RelationshipMetrics(
                familiarity=relationship.familiarity,
                trust=relationship.trust,
                attraction=relationship.attraction,
                admiration=relationship.admiration,
            )
