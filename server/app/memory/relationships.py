"""Rule-based relationship delta updates derived from simulation events."""

from __future__ import annotations

from dataclasses import dataclass

from app.schemas.event import EventType, SimulationEvent


@dataclass(slots=True)
class RelationshipDelta:
    """Directional relationship metric changes for one source->target edge."""

    source_agent_id: str
    target_agent_id: str
    familiarity: float = 0.0
    trust: float = 0.0
    attraction: float = 0.0
    resentment: float = 0.0
    admiration: float = 0.0
    fear: float = 0.0
    obligation: float = 0.0
    dependency: float = 0.0


class RelationshipDeltaUpdater:
    """Map important events into explicit small relationship changes."""

    def deltas_for(self, event: SimulationEvent) -> list[RelationshipDelta]:
        """Return all relationship updates implied by one event."""

        if event.type is EventType.GIFT_GIVEN and event.actor_ids and event.target_ids:
            actor_id = event.actor_ids[0]
            target_id = event.target_ids[0]
            if bool(event.payload.get("target_was_starving")):
                return [
                    RelationshipDelta(
                        source_agent_id=target_id,
                        target_agent_id=actor_id,
                        trust=0.18,
                        obligation=0.22,
                        admiration=0.08,
                        familiarity=0.03,
                    ),
                    RelationshipDelta(
                        source_agent_id=actor_id,
                        target_agent_id=target_id,
                        familiarity=0.04,
                        admiration=0.02,
                    ),
                ]
            return [
                RelationshipDelta(
                    source_agent_id=target_id,
                    target_agent_id=actor_id,
                    trust=0.08,
                    obligation=0.05,
                    admiration=0.04,
                    familiarity=0.03,
                )
            ]

        if event.type is EventType.INSULT_SPOKEN and event.actor_ids and event.target_ids:
            actor_id = event.actor_ids[0]
            target_id = event.target_ids[0]
            public_bonus = 0.02 if bool(event.payload.get("public")) else 0.0
            return [
                RelationshipDelta(
                    source_agent_id=target_id,
                    target_agent_id=actor_id,
                    trust=-0.10,
                    resentment=0.15 + public_bonus,
                    fear=0.03,
                )
            ]

        if event.type is EventType.PROPOSAL_ACCEPTED and event.actor_ids and event.target_ids:
            actor_id = event.actor_ids[0]
            target_id = event.target_ids[0]
            return [
                RelationshipDelta(
                    source_agent_id=actor_id,
                    target_agent_id=target_id,
                    trust=0.12,
                    attraction=0.15,
                    familiarity=0.08,
                    admiration=0.05,
                ),
                RelationshipDelta(
                    source_agent_id=target_id,
                    target_agent_id=actor_id,
                    trust=0.12,
                    attraction=0.15,
                    familiarity=0.08,
                    admiration=0.05,
                ),
            ]

        return []
