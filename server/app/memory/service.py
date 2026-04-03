"""Persistence-aware retrieval helpers for the memory system."""

from __future__ import annotations

import uuid
from typing import Literal

from app.db.repositories.memory import MemoryRepository
from app.schemas.memory import EpisodicMemoryRecord, SemanticBeliefRecord


class MemoryQueryService:
    """Small query facade over the persistent memory repository."""

    def __init__(self, repository: MemoryRepository) -> None:
        self._repository = repository

    def query_episodic_memories(
        self,
        agent_id: uuid.UUID,
        *,
        min_salience: float | None = None,
        min_tick: int | None = None,
        sort_by: Literal["recency", "salience"] = "recency",
        limit: int = 10,
        include_archived: bool = False,
    ) -> list[EpisodicMemoryRecord]:
        """Return serialized episodic memories with salience/recency filters."""

        return [
            EpisodicMemoryRecord.model_validate(memory, from_attributes=True)
            for memory in self._repository.list_memories_for_agent(
                agent_id,
                include_archived=include_archived,
                min_salience=min_salience,
                min_tick=min_tick,
                sort_by=sort_by,
                limit=limit,
            )
        ]

    def query_semantic_beliefs(
        self,
        agent_id: uuid.UUID,
        *,
        subject_type: str | None = None,
        predicate: str | None = None,
        min_confidence: float | None = None,
        limit: int = 10,
    ) -> list[SemanticBeliefRecord]:
        """Return serialized semantic beliefs filtered by subject/predicate/confidence."""

        return [
            SemanticBeliefRecord.model_validate(belief, from_attributes=True)
            for belief in self._repository.list_beliefs_for_agent(
                agent_id,
                subject_type=subject_type,
                predicate=predicate,
                min_confidence=min_confidence,
                limit=limit,
            )
        ]
