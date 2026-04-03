"""Deterministic salience scoring for event-driven memory formation."""

from __future__ import annotations

from dataclasses import dataclass

from app.engine.world_state import AgentState
from app.schemas.event import EventType, SimulationEvent


BASE_EVENT_WEIGHTS: dict[EventType, float] = {
    EventType.AGENT_DIED: 1.00,
    EventType.CHILD_BORN: 0.95,
    EventType.CROP_FAILED: 0.85,
    EventType.FOOD_STORE_EMPTY: 0.85,
    EventType.PROPOSAL_ACCEPTED: 0.75,
    EventType.INSULT_SPOKEN: 0.70,
    EventType.GIFT_GIVEN: 0.65,
    EventType.PREGNANCY_STARTED: 0.72,
    EventType.PROPOSAL_MADE: 0.50,
    EventType.AGENT_ATE: 0.20,
    EventType.AGENT_DRANK: 0.20,
}


@dataclass(slots=True)
class SalienceComponents:
    """Structured salience breakdown for debugging and tests."""

    base_event_weight: float
    novelty_bonus: float
    relationship_intensity_bonus: float
    survival_relevance_bonus: float
    emotional_impact_bonus: float

    @property
    def total(self) -> float:
        """Return the unclamped sum of all salience inputs."""

        return (
            self.base_event_weight
            + self.novelty_bonus
            + self.relationship_intensity_bonus
            + self.survival_relevance_bonus
            + self.emotional_impact_bonus
        )


class EventSalienceScorer:
    """Apply a readable rule-based salience policy to simulation events."""

    def score(self, event: SimulationEvent, *, agent: AgentState | None = None) -> float:
        """Return a bounded [0, 1] salience score."""

        return max(0.0, min(1.0, self.components_for(event, agent=agent).total))

    def components_for(
        self,
        event: SimulationEvent,
        *,
        agent: AgentState | None = None,
    ) -> SalienceComponents:
        """Return the score breakdown for one event/agent perspective."""

        return SalienceComponents(
            base_event_weight=BASE_EVENT_WEIGHTS.get(event.type, 0.10),
            novelty_bonus=self._novelty_bonus(event, agent),
            relationship_intensity_bonus=self._relationship_intensity_bonus(event, agent),
            survival_relevance_bonus=self._survival_relevance_bonus(event, agent),
            emotional_impact_bonus=self._emotional_impact_bonus(event, agent),
        )

    @staticmethod
    def _novelty_bonus(event: SimulationEvent, agent: AgentState | None) -> float:
        if agent is None:
            return 0.08
        marker = {
            EventType.AGENT_ATE: "ate",
            EventType.AGENT_DRANK: "drank",
            EventType.GIFT_GIVEN: "gave",
            EventType.INSULT_SPOKEN: "insult",
            EventType.PROPOSAL_MADE: "proposed",
            EventType.PROPOSAL_ACCEPTED: "committed",
            EventType.PREGNANCY_STARTED: "pregnancy",
            EventType.CHILD_BORN: "born",
            EventType.AGENT_DIED: "died",
            EventType.FOOD_STORE_EMPTY: "food source ran dry",
            EventType.CROP_FAILED: "crop failed",
        }.get(event.type, event.type.value.replace("_", " "))
        recent = " ".join(memory.lower() for memory in agent.memories[-5:])
        return 0.0 if marker in recent else 0.10

    @staticmethod
    def _relationship_intensity_bonus(event: SimulationEvent, agent: AgentState | None) -> float:
        if not event.actor_ids and not event.target_ids:
            return 0.0
        bonus = 0.08 if event.actor_ids and event.target_ids else 0.0
        if agent is not None and agent.partner_id is not None:
            participants = set(event.actor_ids) | set(event.target_ids)
            if agent.partner_id in participants:
                bonus += 0.08
        return bonus

    @staticmethod
    def _survival_relevance_bonus(event: SimulationEvent, agent: AgentState | None) -> float:
        bonus = 0.0
        if event.type in {
            EventType.AGENT_ATE,
            EventType.AGENT_DRANK,
            EventType.FOOD_STORE_EMPTY,
            EventType.CROP_FAILED,
            EventType.AGENT_DIED,
        }:
            bonus += 0.18
        if bool(event.payload.get("target_was_starving")):
            bonus += 0.15
        if agent is not None and max(agent.hunger, agent.thirst, agent.fatigue) >= 85.0:
            bonus += 0.07
        return bonus

    @staticmethod
    def _emotional_impact_bonus(event: SimulationEvent, agent: AgentState | None) -> float:
        base = {
            EventType.AGENT_DIED: 0.20,
            EventType.CHILD_BORN: 0.18,
            EventType.PREGNANCY_STARTED: 0.10,
            EventType.PROPOSAL_ACCEPTED: 0.12,
            EventType.INSULT_SPOKEN: 0.12,
            EventType.GIFT_GIVEN: 0.08,
            EventType.FOOD_STORE_EMPTY: 0.14,
            EventType.CROP_FAILED: 0.16,
        }.get(event.type, 0.0)
        if agent is not None and event.type is EventType.INSULT_SPOKEN and agent.agent_id in event.target_ids:
            base += 0.05
        return base
