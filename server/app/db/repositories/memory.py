"""Repository helpers for episodic memories, beliefs, and embeddings."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import EpisodicMemory, MemoryEmbedding, SemanticBelief


@dataclass(slots=True)
class EpisodicMemoryCreateParams:
    """Parameters for creating an episodic memory record."""

    agent_id: uuid.UUID
    tick: int
    event_type: str
    raw_text: str
    valence: float
    salience: float
    location_x: int | None = None
    location_y: int | None = None
    participant_ids: list[uuid.UUID] = field(default_factory=list)
    decay_rate: float = 0.01
    archived: bool = False


@dataclass(slots=True)
class SemanticBeliefCreateParams:
    """Parameters for creating a semantic belief record."""

    agent_id: uuid.UUID
    subject_type: str
    predicate: str
    object_value: str
    confidence: float
    last_supported_tick: int
    subject_id: uuid.UUID | None = None
    evidence_count: int = 1


@dataclass(slots=True)
class EmbeddedMemoryRecord:
    """Joined episodic-memory row and embedding vector for retrieval-time similarity search."""

    memory: EpisodicMemory
    embedding: list[float]


class MemoryRepository:
    """Persistence helper for memory-oriented records."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_memory(self, memory: EpisodicMemory) -> EpisodicMemory:
        """Persist an episodic memory row."""

        self._session.add(memory)
        self._session.flush()
        return memory

    def add_belief(self, belief: SemanticBelief) -> SemanticBelief:
        """Persist a semantic belief row."""

        self._session.add(belief)
        self._session.flush()
        return belief

    def attach_embedding(self, embedding: MemoryEmbedding) -> MemoryEmbedding:
        """Persist an embedding row for an episodic memory."""

        self._session.add(embedding)
        self._session.flush()
        return embedding

    def create_memory(self, params: EpisodicMemoryCreateParams) -> EpisodicMemory:
        """Create and persist an episodic memory row."""

        memory = EpisodicMemory(
            agent_id=params.agent_id,
            tick=params.tick,
            event_type=params.event_type,
            location_x=params.location_x,
            location_y=params.location_y,
            raw_text=params.raw_text,
            valence=params.valence,
            salience=params.salience,
            participant_ids=params.participant_ids,
            decay_rate=params.decay_rate,
            archived=params.archived,
        )
        return self.add_memory(memory)

    def list_memories_for_agent(
        self,
        agent_id: uuid.UUID,
        *,
        include_archived: bool = False,
        min_salience: float | None = None,
        min_tick: int | None = None,
        sort_by: Literal["recency", "salience"] = "recency",
        limit: int | None = None,
    ) -> list[EpisodicMemory]:
        """List episodic memories for an agent, newest tick first."""

        statement = select(EpisodicMemory).where(EpisodicMemory.agent_id == agent_id)
        if not include_archived:
            statement = statement.where(EpisodicMemory.archived.is_(False))
        if min_salience is not None:
            statement = statement.where(EpisodicMemory.salience >= min_salience)
        if min_tick is not None:
            statement = statement.where(EpisodicMemory.tick >= min_tick)
        if sort_by == "salience":
            statement = statement.order_by(EpisodicMemory.salience.desc(), EpisodicMemory.tick.desc(), EpisodicMemory.id)
        else:
            statement = statement.order_by(EpisodicMemory.tick.desc(), EpisodicMemory.salience.desc(), EpisodicMemory.id)
        if limit is not None:
            statement = statement.limit(limit)
        return list(self._session.scalars(statement))

    def create_belief(self, params: SemanticBeliefCreateParams) -> SemanticBelief:
        """Create and persist a semantic belief row."""

        belief = SemanticBelief(
            agent_id=params.agent_id,
            subject_type=params.subject_type,
            subject_id=params.subject_id,
            predicate=params.predicate,
            object_value=params.object_value,
            confidence=params.confidence,
            evidence_count=params.evidence_count,
            last_supported_tick=params.last_supported_tick,
        )
        return self.add_belief(belief)

    def get_matching_belief(
        self,
        *,
        agent_id: uuid.UUID,
        subject_type: str,
        predicate: str,
        object_value: str,
        subject_id: uuid.UUID | None = None,
    ) -> SemanticBelief | None:
        """Return an existing belief row that matches the semantic identity."""

        statement = select(SemanticBelief).where(
            SemanticBelief.agent_id == agent_id,
            SemanticBelief.subject_type == subject_type,
            SemanticBelief.subject_id == subject_id,
            SemanticBelief.predicate == predicate,
            SemanticBelief.object_value == object_value,
        )
        return self._session.scalar(statement)

    def support_belief(
        self,
        *,
        agent_id: uuid.UUID,
        subject_type: str,
        predicate: str,
        object_value: str,
        confidence: float,
        last_supported_tick: int,
        subject_id: uuid.UUID | None = None,
    ) -> SemanticBelief:
        """Insert or reinforce a semantic belief row deterministically."""

        belief = self.get_matching_belief(
            agent_id=agent_id,
            subject_type=subject_type,
            subject_id=subject_id,
            predicate=predicate,
            object_value=object_value,
        )
        if belief is None:
            return self.create_belief(
                SemanticBeliefCreateParams(
                    agent_id=agent_id,
                    subject_type=subject_type,
                    subject_id=subject_id,
                    predicate=predicate,
                    object_value=object_value,
                    confidence=confidence,
                    last_supported_tick=last_supported_tick,
                )
            )
        belief.evidence_count += 1
        belief.last_supported_tick = last_supported_tick
        belief.confidence = min(1.0, max(belief.confidence, confidence) + 0.05)
        self._session.flush()
        return belief

    def list_beliefs_for_agent(
        self,
        agent_id: uuid.UUID,
        *,
        subject_type: str | None = None,
        predicate: str | None = None,
        min_confidence: float | None = None,
        limit: int | None = None,
    ) -> list[SemanticBelief]:
        """List semantic beliefs for an agent."""

        statement = select(SemanticBelief).where(SemanticBelief.agent_id == agent_id)
        if subject_type is not None:
            statement = statement.where(SemanticBelief.subject_type == subject_type)
        if predicate is not None:
            statement = statement.where(SemanticBelief.predicate == predicate)
        if min_confidence is not None:
            statement = statement.where(SemanticBelief.confidence >= min_confidence)
        statement = statement.order_by(
            SemanticBelief.confidence.desc(),
            SemanticBelief.last_supported_tick.desc(),
            SemanticBelief.id,
        )
        if limit is not None:
            statement = statement.limit(limit)
        return list(self._session.scalars(statement))

    def list_embedded_memories_for_agent(
        self,
        agent_id: uuid.UUID,
        *,
        include_archived: bool = False,
        limit: int | None = None,
    ) -> list[EmbeddedMemoryRecord]:
        """Return episodic memories that have embeddings attached for one agent."""

        statement = (
            select(EpisodicMemory, MemoryEmbedding.embedding)
            .join(MemoryEmbedding, MemoryEmbedding.memory_id == EpisodicMemory.id)
            .where(EpisodicMemory.agent_id == agent_id)
        )
        if not include_archived:
            statement = statement.where(EpisodicMemory.archived.is_(False))
        statement = statement.order_by(
            EpisodicMemory.tick.desc(),
            EpisodicMemory.salience.desc(),
            EpisodicMemory.id,
        )
        if limit is not None:
            statement = statement.limit(limit)
        return [
            EmbeddedMemoryRecord(memory=memory, embedding=embedding)
            for memory, embedding in self._session.execute(statement).all()
        ]
