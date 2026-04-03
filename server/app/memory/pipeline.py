"""Event-driven memory pipeline for authoritative world events."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
import uuid

from sqlalchemy.orm import Session

from app.db.repositories.agents import AgentRepository, RelationshipCreateParams
from app.db.repositories.memory import MemoryRepository, EpisodicMemoryCreateParams
from app.engine.world_state import AgentState, WorldState
from app.memory.beliefs import BeliefEvidence, SemanticBeliefProjector
from app.memory.embeddings import EmbeddingProvider, NullEmbeddingProvider
from app.memory.relationships import RelationshipDelta, RelationshipDeltaUpdater
from app.memory.salience import EventSalienceScorer
from app.memory.summary_queue import DailySummaryQueue
from app.memory.writer import MemoryWriter
from app.schemas.event import EventType, SimulationEvent
from app.schemas.reflection import MemoryCandidate

AgentIdResolver = Callable[[str], uuid.UUID | None]


IMPORTANT_MEMORY_EVENTS = {
    EventType.AGENT_ATE,
    EventType.AGENT_DRANK,
    EventType.GIFT_GIVEN,
    EventType.INSULT_SPOKEN,
    EventType.PROPOSAL_MADE,
    EventType.PROPOSAL_ACCEPTED,
    EventType.PREGNANCY_STARTED,
    EventType.CHILD_BORN,
    EventType.AGENT_DIED,
    EventType.FOOD_STORE_EMPTY,
    EventType.CROP_FAILED,
}


@dataclass(slots=True)
class MemoryWriteIntent:
    """One per-agent episodic memory derived from a world event."""

    agent_id: str
    text: str
    valence: float
    salience: float
    participants: list[str]
    location_x: int | None
    location_y: int | None


class MemoryPipelineListener:
    """Orchestrate event -> salience -> memory/belief/relationship/embedding/summary writes."""

    def __init__(
        self,
        world_getter: Callable[[], WorldState],
        *,
        memory_writer: MemoryWriter | None = None,
        salience_scorer: EventSalienceScorer | None = None,
        relationship_updater: RelationshipDeltaUpdater | None = None,
        belief_projector: SemanticBeliefProjector | None = None,
        embedding_provider: EmbeddingProvider | None = None,
        summary_queue: DailySummaryQueue | None = None,
        session_scope: Callable[[], AbstractContextManager[Session]] | None = None,
        resolve_agent_id: AgentIdResolver | None = None,
    ) -> None:
        self._world_getter = world_getter
        self._memory_writer = memory_writer or MemoryWriter()
        self._salience_scorer = salience_scorer or EventSalienceScorer()
        self._relationship_updater = relationship_updater or RelationshipDeltaUpdater()
        self._belief_projector = belief_projector or SemanticBeliefProjector()
        self._embedding_provider = embedding_provider or NullEmbeddingProvider()
        self._summary_queue = summary_queue or DailySummaryQueue()
        self._session_scope = session_scope
        self._resolve_agent_id = resolve_agent_id
        self._seen_event_ids: set[str] = set()

    def handle(self, event: SimulationEvent) -> None:
        """Process one authoritative event through the full memory pipeline."""

        if event.event_id is not None and event.event_id in self._seen_event_ids:
            return
        if event.type not in IMPORTANT_MEMORY_EVENTS:
            if event.event_id is not None:
                self._seen_event_ids.add(event.event_id)
            return

        world = self._world_getter()
        intents = self._build_memory_intents(world, event)
        belief_evidence = self._belief_projector.beliefs_for(event)
        relationship_deltas = self._relationship_updater.deltas_for(event)

        if self._session_scope is not None and self._resolve_agent_id is not None:
            self._persist_outputs(event, intents, belief_evidence, relationship_deltas)

        self._apply_in_memory(world, event, intents, belief_evidence)

        if event.event_id is not None:
            self._seen_event_ids.add(event.event_id)

    def _build_memory_intents(self, world: WorldState, event: SimulationEvent) -> list[MemoryWriteIntent]:
        participants = list(dict.fromkeys([*event.actor_ids, *event.target_ids]))
        intents: list[MemoryWriteIntent] = []
        for agent_id in participants:
            agent = world.agent_by_id(agent_id)
            if agent is None:
                continue
            intents.append(
                MemoryWriteIntent(
                    agent_id=agent_id,
                    text=self._describe_event(event, perspective_agent_id=agent_id),
                    valence=self._valence_for(event, perspective_agent_id=agent_id),
                    salience=self._salience_scorer.score(event, agent=agent),
                    participants=participants,
                    location_x=event.location_x,
                    location_y=event.location_y,
                )
            )
        return intents

    def _apply_in_memory(
        self,
        world: WorldState,
        event: SimulationEvent,
        intents: list[MemoryWriteIntent],
        belief_evidence: list[BeliefEvidence],
    ) -> None:
        for intent in intents:
            agent = world.agent_by_id(intent.agent_id)
            if agent is None:
                continue
            self._memory_writer.write(agent, [intent.text])
            self._summary_queue.enqueue(
                agent,
                day_index=world.day_index,
                candidate=MemoryCandidate(
                    text=intent.text,
                    salience=intent.salience,
                    valence=intent.valence,
                ),
            )

        for evidence in belief_evidence:
            agent = world.agent_by_id(evidence.agent_id)
            if agent is None:
                continue
            belief_text = evidence.to_agent_belief_text()
            if belief_text not in agent.beliefs:
                agent.beliefs.append(belief_text)

    def _persist_outputs(
        self,
        event: SimulationEvent,
        intents: list[MemoryWriteIntent],
        belief_evidence: list[BeliefEvidence],
        relationship_deltas: list[RelationshipDelta],
    ) -> None:
        assert self._session_scope is not None
        assert self._resolve_agent_id is not None

        with self._session_scope() as session:
            memory_repository = MemoryRepository(session)
            agent_repository = AgentRepository(session)
            known_agents: dict[uuid.UUID, bool] = {}

            def agent_exists(agent_uuid: uuid.UUID | None) -> bool:
                if agent_uuid is None:
                    return False
                if agent_uuid not in known_agents:
                    known_agents[agent_uuid] = agent_repository.get_agent_with_related(agent_uuid) is not None
                return known_agents[agent_uuid]

            for intent in intents:
                agent_uuid = self._resolve_agent_id(intent.agent_id)
                if not agent_exists(agent_uuid):
                    continue
                participant_ids = [
                    resolved
                    for participant_id in intent.participants
                    if (resolved := self._resolve_agent_id(participant_id)) is not None and agent_exists(resolved)
                ]
                memory = memory_repository.create_memory(
                    EpisodicMemoryCreateParams(
                        agent_id=agent_uuid,
                        tick=event.tick,
                        event_type=event.type.value,
                        raw_text=intent.text,
                        valence=intent.valence,
                        salience=intent.salience,
                        location_x=intent.location_x,
                        location_y=intent.location_y,
                        participant_ids=participant_ids,
                    )
                )
                embedding = self._embedding_provider.embed_text(intent.text)
                if embedding is not None:
                    memory_repository.attach_embedding(
                        embedding=self._build_embedding_row(
                            memory_id=memory.id,
                            agent_id=agent_uuid,
                            embedding=embedding,
                        )
                    )

            for evidence in belief_evidence:
                agent_uuid = self._resolve_agent_id(evidence.agent_id)
                subject_uuid = (
                    self._resolve_agent_id(evidence.subject_id)
                    if evidence.subject_id is not None
                    else None
                )
                if not agent_exists(agent_uuid):
                    continue
                if evidence.subject_type == "agent" and not agent_exists(subject_uuid):
                    continue
                memory_repository.support_belief(
                    agent_id=agent_uuid,
                    subject_type=evidence.subject_type,
                    subject_id=subject_uuid,
                    predicate=evidence.predicate,
                    object_value=evidence.object_value,
                    confidence=evidence.confidence,
                    last_supported_tick=event.tick,
                )

            for delta in relationship_deltas:
                source_uuid = self._resolve_agent_id(delta.source_agent_id)
                target_uuid = self._resolve_agent_id(delta.target_agent_id)
                if not agent_exists(source_uuid) or not agent_exists(target_uuid):
                    continue
                relationship = agent_repository.get_relationship(source_uuid, target_uuid)
                if relationship is None:
                    relationship = agent_repository.create_relationship(
                        RelationshipCreateParams(
                            source_agent_id=source_uuid,
                            target_agent_id=target_uuid,
                            last_interaction_tick=event.tick,
                        )
                    )
                relationship.familiarity = _clamp_unit_interval(relationship.familiarity + delta.familiarity)
                relationship.trust = _clamp_unit_interval(relationship.trust + delta.trust)
                relationship.attraction = _clamp_unit_interval(relationship.attraction + delta.attraction)
                relationship.resentment = _clamp_unit_interval(relationship.resentment + delta.resentment)
                relationship.admiration = _clamp_unit_interval(relationship.admiration + delta.admiration)
                relationship.fear = _clamp_unit_interval(relationship.fear + delta.fear)
                relationship.obligation = _clamp_unit_interval(relationship.obligation + delta.obligation)
                relationship.dependency = _clamp_unit_interval(relationship.dependency + delta.dependency)
                relationship.last_interaction_tick = event.tick

    @staticmethod
    def _build_embedding_row(*, memory_id: uuid.UUID, agent_id: uuid.UUID, embedding: list[float]):
        from app.db.models import MemoryEmbedding

        return MemoryEmbedding(memory_id=memory_id, agent_id=agent_id, embedding=embedding)

    @staticmethod
    def _describe_event(event: SimulationEvent, *, perspective_agent_id: str) -> str:
        actor = event.actor_ids[0] if event.actor_ids else "someone"
        target = event.target_ids[0] if event.target_ids else "someone"
        item_type = str(event.payload.get("item_type", "a gift"))

        if event.type is EventType.AGENT_ATE:
            return "Ate a meal."
        if event.type is EventType.AGENT_DRANK:
            return "Drank fresh water."
        if event.type is EventType.GIFT_GIVEN:
            if perspective_agent_id == actor:
                return f"Gave {item_type} to {target}."
            if perspective_agent_id == target:
                return f"{actor} gave me {item_type}."
            return f"{actor} gave {item_type} to {target}."
        if event.type is EventType.INSULT_SPOKEN:
            if perspective_agent_id == actor:
                return f"Insulted {target}."
            if perspective_agent_id == target:
                return f"{actor} insulted me."
            return f"{actor} insulted {target}."
        if event.type is EventType.PROPOSAL_MADE:
            return f"{actor} proposed to {target}."
        if event.type is EventType.PROPOSAL_ACCEPTED:
            return f"{actor} and {target} committed to each other."
        if event.type is EventType.PREGNANCY_STARTED:
            return "Pregnancy began."
        if event.type is EventType.CHILD_BORN:
            child_id = event.payload.get("child_id", "a child")
            return f"{child_id} was born."
        if event.type is EventType.AGENT_DIED:
            return f"{actor} died."
        if event.type is EventType.FOOD_STORE_EMPTY:
            return "A nearby food source ran dry."
        if event.type is EventType.CROP_FAILED:
            return "A nearby crop failed."
        return event.type.value.replace("_", " ")

    @staticmethod
    def _valence_for(event: SimulationEvent, *, perspective_agent_id: str) -> float:
        if event.type is EventType.AGENT_ATE:
            return 0.25
        if event.type is EventType.AGENT_DRANK:
            return 0.25
        if event.type is EventType.GIFT_GIVEN:
            if event.target_ids and perspective_agent_id == event.target_ids[0]:
                return 0.70
            return 0.35
        if event.type is EventType.INSULT_SPOKEN:
            if event.target_ids and perspective_agent_id == event.target_ids[0]:
                return -0.80
            return -0.35
        if event.type is EventType.PROPOSAL_MADE:
            return 0.45
        if event.type is EventType.PROPOSAL_ACCEPTED:
            return 0.80
        if event.type is EventType.PREGNANCY_STARTED:
            return 0.70
        if event.type is EventType.CHILD_BORN:
            return 0.90
        if event.type is EventType.AGENT_DIED:
            return -0.95
        if event.type is EventType.FOOD_STORE_EMPTY:
            return -0.55
        if event.type is EventType.CROP_FAILED:
            return -0.75
        return 0.0


def _clamp_unit_interval(value: float) -> float:
    """Clamp one relationship metric to the supported [0, 1] interval."""

    return max(0.0, min(1.0, value))
