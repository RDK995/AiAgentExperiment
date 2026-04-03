"""Rule-based semantic belief updates derived from authoritative events."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.event import EventType, SimulationEvent


@dataclass(slots=True)
class BeliefEvidence:
    """One semantic belief supported by an event from one agent perspective."""

    agent_id: str
    subject_type: str
    predicate: str
    object_value: str
    subject_id: str | None = None
    confidence: float = 0.60

    def to_agent_belief_text(self) -> str:
        """Project the structured belief into the current in-memory string contract."""

        if self.subject_id is None:
            return f"{self.subject_type}:{self.predicate}:{self.object_value}"
        return f"{self.subject_type}:{self.subject_id}:{self.predicate}:{self.object_value}"


class SemanticBeliefProjector:
    """Convert repeated meaningful events into compact structured beliefs."""

    def beliefs_for(self, event: SimulationEvent) -> list[BeliefEvidence]:
        """Return structured belief evidence implied by one event."""

        if event.type is EventType.GIFT_GIVEN and event.actor_ids and event.target_ids:
            actor_id = event.actor_ids[0]
            target_id = event.target_ids[0]
            beliefs = [
                BeliefEvidence(
                    agent_id=target_id,
                    subject_type="agent",
                    subject_id=actor_id,
                    predicate="is_generous",
                    object_value="yes",
                    confidence=0.65 if not bool(event.payload.get("target_was_starving")) else 0.78,
                )
            ]
            if bool(event.payload.get("target_was_starving")):
                beliefs.append(
                    BeliefEvidence(
                        agent_id=target_id,
                        subject_type="agent",
                        subject_id=actor_id,
                        predicate="helped_me_when_hungry",
                        object_value="yes",
                        confidence=0.82,
                    )
                )
            return beliefs

        if event.type is EventType.INSULT_SPOKEN and event.actor_ids and event.target_ids:
            return [
                BeliefEvidence(
                    agent_id=event.target_ids[0],
                    subject_type="agent",
                    subject_id=event.actor_ids[0],
                    predicate="is_hostile",
                    object_value="yes",
                    confidence=0.80,
                )
            ]

        if event.type in {EventType.FOOD_STORE_EMPTY, EventType.CROP_FAILED}:
            affected_agents = list(dict.fromkeys([*event.actor_ids, *event.target_ids]))
            scarcity_key = f"food_near_{event.location_x}_{event.location_y}"
            return [
                BeliefEvidence(
                    agent_id=agent_id,
                    subject_type="world",
                    predicate="resource_scarcity",
                    object_value=scarcity_key,
                    confidence=0.72 if event.type is EventType.FOOD_STORE_EMPTY else 0.78,
                )
                for agent_id in affected_agents
            ]

        return []
