"""Retrieval pipeline helpers for reflection and dialogue context assembly."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from math import sqrt
import uuid

from sqlalchemy.orm import Session

from app.cognition.reflection_graph import AutobiographyBuilder
from app.db.enums import GoalStatus
from app.db.models import AgentGoal, Relationship
from app.db.repositories.agents import AgentRepository
from app.db.repositories.memory import EmbeddedMemoryRecord, MemoryRepository
from app.engine.world_state import AgentState
from app.memory.embeddings import EmbeddingProvider
from app.memory.retriever import MemoryRetriever
from app.schemas.memory import (
    RetrievalContextResult,
    RetrievedGoalRecord,
    RetrievedMemoryRecord,
    RetrievedRelationshipRecord,
)


@dataclass(slots=True)
class _PersistentContextSlice:
    """Optional persistence-backed retrieval slice for one agent."""

    summary: str | None
    goals: list[RetrievedGoalRecord]
    relationships: list[RetrievedRelationshipRecord]
    recent_memories: list[RetrievedMemoryRecord]
    similar_memories: list[RetrievedMemoryRecord]


class RetrievalContextService:
    """Assemble compact retrieval context for reflection or future dialogue."""

    def __init__(
        self,
        *,
        memory_retriever: MemoryRetriever | None = None,
        autobiography_builder: AutobiographyBuilder | None = None,
        session_scope: Callable[[], AbstractContextManager[Session]] | None = None,
        persistent_agent_id_resolver: Callable[[str], uuid.UUID | None] | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._memory_retriever = memory_retriever or MemoryRetriever()
        self._autobiography_builder = autobiography_builder or AutobiographyBuilder()
        self._session_scope = session_scope
        self._persistent_agent_id_resolver = persistent_agent_id_resolver
        self._embedding_provider = embedding_provider

    def retrieve_context(
        self,
        agent: AgentState,
        *,
        query_text: str,
        relationship_limit: int = 5,
        recent_limit: int = 8,
        similar_limit: int = 8,
        final_memory_limit: int = 12,
    ) -> RetrievalContextResult:
        """Collect summary, goals, relationships, and reranked memories for one agent."""

        runtime_recent = self._get_runtime_recent_memories(agent, limit=recent_limit)
        persistent_slice = self._get_persistent_slice(
            agent,
            query_text=query_text,
            relationship_limit=relationship_limit,
            recent_limit=recent_limit,
            similar_limit=similar_limit,
        )
        merged_memories = rerank_memories(
            runtime_recent + persistent_slice.recent_memories,
            persistent_slice.similar_memories,
            final_limit=final_memory_limit,
        )
        summary = persistent_slice.summary
        if not summary:
            summary = self._autobiography_builder.build(
                agent,
                [memory.raw_text for memory in merged_memories[:3]],
            )

        goals = persistent_slice.goals or self._get_runtime_goals(agent)
        relationships = persistent_slice.relationships or self._get_runtime_relationships(agent)
        return RetrievalContextResult(
            summary=summary,
            goals=goals,
            relationships=relationships,
            memories=merged_memories,
        )

    def _get_persistent_slice(
        self,
        agent: AgentState,
        *,
        query_text: str,
        relationship_limit: int,
        recent_limit: int,
        similar_limit: int,
    ) -> _PersistentContextSlice:
        agent_uuid = self._resolve_persistent_agent_id(agent.agent_id)
        if agent_uuid is None or self._session_scope is None:
            return _PersistentContextSlice(
                summary=None,
                goals=[],
                relationships=[],
                recent_memories=[],
                similar_memories=[],
            )

        with self._session_scope() as session:
            agent_repository = AgentRepository(session)
            memory_repository = MemoryRepository(session)
            persistent_agent = agent_repository.get_agent_with_related(agent_uuid)
            summary = None
            if persistent_agent is not None and persistent_agent.biography_summary.strip():
                summary = persistent_agent.biography_summary.strip()
            goals = self._get_persistent_goals(agent_repository, agent_uuid)
            relationships = self._get_persistent_relationships(
                agent_repository,
                agent_uuid,
                limit=relationship_limit,
            )
            recent_memories = self._get_persistent_recent_memories(
                memory_repository,
                agent_uuid,
                limit=recent_limit,
            )
            similar_memories = self._search_similar_memories(
                memory_repository,
                agent_uuid,
                query_text=query_text,
                limit=similar_limit,
            )
            return _PersistentContextSlice(
                summary=summary,
                goals=goals,
                relationships=relationships,
                recent_memories=recent_memories,
                similar_memories=similar_memories,
            )

    def _get_runtime_recent_memories(self, agent: AgentState, *, limit: int) -> list[RetrievedMemoryRecord]:
        candidate_by_text = {candidate.text: candidate for candidate in agent.daily_summary_candidates}
        recent_texts = self._memory_retriever.retrieve_recent_events(agent)[:limit]
        return [
            RetrievedMemoryRecord(
                raw_text=text,
                salience=candidate_by_text[text].salience if text in candidate_by_text else 0.0,
                valence=candidate_by_text[text].valence if text in candidate_by_text else 0.0,
            )
            for text in recent_texts
        ]

    @staticmethod
    def _get_runtime_goals(agent: AgentState) -> list[RetrievedGoalRecord]:
        if not agent.current_goal:
            return []
        return [
            RetrievedGoalRecord(
                title=agent.current_goal,
                priority=1.0,
                status="active",
            )
        ]

    @staticmethod
    def _get_runtime_relationships(agent: AgentState) -> list[RetrievedRelationshipRecord]:
        if not agent.partner_id:
            return []
        return [
            RetrievedRelationshipRecord(
                related_agent_id=agent.partner_id,
                score=1.0,
                trust=1.0,
                admiration=1.0,
                familiarity=1.0,
                attraction=1.0,
                obligation=0.8,
                resentment=0.0,
                fear=0.0,
                dependency=0.0,
                last_interaction_tick=None,
            )
        ]

    @staticmethod
    def _get_persistent_goals(
        agent_repository: AgentRepository,
        agent_id: uuid.UUID,
    ) -> list[RetrievedGoalRecord]:
        goals = agent_repository.list_goals_for_agent(agent_id, status=GoalStatus.ACTIVE)
        return [
            RetrievedGoalRecord(
                title=goal.title,
                priority=goal.priority,
                status=goal.status.value,
            )
            for goal in goals
        ]

    def _get_persistent_relationships(
        self,
        agent_repository: AgentRepository,
        agent_id: uuid.UUID,
        *,
        limit: int,
    ) -> list[RetrievedRelationshipRecord]:
        relationships = [
            relationship
            for relationship in agent_repository.list_relationships_for_agent(agent_id)
            if relationship.source_agent_id == agent_id
        ]
        ranked = sorted(
            relationships,
            key=lambda relationship: (
                -score_relationship(relationship),
                -(relationship.last_interaction_tick or -1),
                str(relationship.target_agent_id),
            ),
        )
        return [
            RetrievedRelationshipRecord(
                related_agent_id=str(relationship.target_agent_id),
                score=score_relationship(relationship),
                trust=relationship.trust,
                admiration=relationship.admiration,
                familiarity=relationship.familiarity,
                attraction=relationship.attraction,
                obligation=relationship.obligation,
                resentment=relationship.resentment,
                fear=relationship.fear,
                dependency=relationship.dependency,
                last_interaction_tick=relationship.last_interaction_tick,
            )
            for relationship in ranked[:limit]
        ]

    def _get_persistent_recent_memories(
        self,
        memory_repository: MemoryRepository,
        agent_id: uuid.UUID,
        *,
        limit: int,
    ) -> list[RetrievedMemoryRecord]:
        memories = memory_repository.list_memories_for_agent(
            agent_id,
            sort_by="recency",
            limit=limit,
        )
        return [self._serialize_memory(memory) for memory in memories]

    def _search_similar_memories(
        self,
        memory_repository: MemoryRepository,
        agent_id: uuid.UUID,
        *,
        query_text: str,
        limit: int,
    ) -> list[RetrievedMemoryRecord]:
        if self._embedding_provider is None or not query_text.strip():
            return []
        try:
            query_embedding = self._embedding_provider.embed_text(query_text)
        except Exception:
            return []
        if query_embedding is None:
            return []

        candidates = memory_repository.list_embedded_memories_for_agent(agent_id, limit=limit * 4)
        scored = [
            (
                cosine_similarity(query_embedding, candidate.embedding),
                candidate,
            )
            for candidate in candidates
        ]
        ranked = sorted(
            scored,
            key=lambda item: (
                -item[0],
                -item[1].memory.tick,
                -item[1].memory.salience,
                str(item[1].memory.id),
            ),
        )
        similar_memories: list[RetrievedMemoryRecord] = []
        for similarity, candidate in ranked[:limit]:
            memory_record = self._serialize_memory(candidate.memory)
            similar_memories.append(
                memory_record.model_copy(update={"similarity_score": similarity})
            )
        return similar_memories

    def _resolve_persistent_agent_id(self, agent_id: str) -> uuid.UUID | None:
        if self._persistent_agent_id_resolver is None:
            return None
        return self._persistent_agent_id_resolver(agent_id)

    @staticmethod
    def _serialize_memory(memory) -> RetrievedMemoryRecord:
        return RetrievedMemoryRecord(
            id=str(memory.id),
            raw_text=memory.raw_text,
            tick=memory.tick,
            salience=memory.salience,
            valence=memory.valence,
            location_x=memory.location_x,
            location_y=memory.location_y,
            participant_ids=[str(participant_id) for participant_id in memory.participant_ids],
        )


def rerank_memories(
    recent_memories: list[RetrievedMemoryRecord],
    similar_memories: list[RetrievedMemoryRecord],
    *,
    final_limit: int = 12,
) -> list[RetrievedMemoryRecord]:
    """Merge, deduplicate, rerank, and cap retrieved memories deterministically."""

    if final_limit <= 0:
        return []

    merged_sources = [
        ("recent", memory)
        for memory in recent_memories
    ] + [
        ("similar", memory)
        for memory in similar_memories
    ]
    deduplicated: dict[str, tuple[set[str], RetrievedMemoryRecord]] = {}
    identity_by_text: dict[str, str] = {}
    max_tick = max((memory.tick or 0) for _, memory in merged_sources) if merged_sources else 0
    min_tick = min((memory.tick or 0) for _, memory in merged_sources) if merged_sources else 0

    for source, memory in merged_sources:
        text_identity = f"text:{memory.raw_text}"
        aliased_identity = identity_by_text.get(text_identity)
        if aliased_identity is not None:
            _, aliased_memory = deduplicated[aliased_identity]
            if memory.id is None or aliased_memory.id is None:
                identity = aliased_identity
            else:
                identity = memory.id or text_identity
        else:
            identity = memory.id or text_identity
        sources, existing = deduplicated.get(identity, (set(), None))
        sources.add(source)
        if existing is None:
            deduplicated[identity] = (sources, memory)
            identity_by_text.setdefault(text_identity, identity)
            continue
        deduplicated[identity] = (
            sources,
            existing.model_copy(
                update={
                    "id": existing.id or memory.id,
                    "similarity_score": max(
                        existing.similarity_score or 0.0,
                        memory.similarity_score or 0.0,
                    ),
                    "salience": max(existing.salience, memory.salience),
                    "tick": max(existing.tick or 0, memory.tick or 0) or None,
                    "valence": existing.valence if abs(existing.valence) >= abs(memory.valence) else memory.valence,
                }
            ),
        )
        identity_by_text.setdefault(text_identity, identity)

    scored: list[RetrievedMemoryRecord] = []
    tick_span = max(max_tick - min_tick, 1)
    for identity, (sources, memory) in deduplicated.items():
        recency_component = ((memory.tick or min_tick) - min_tick) / tick_span if max_tick else 0.0
        similarity_component = memory.similarity_score or 0.0
        source_bonus = 0.05 if {"recent", "similar"} <= sources else 0.0
        rerank_score = (
            similarity_component * 0.50
            + memory.salience * 0.35
            + recency_component * 0.15
            + source_bonus
        )
        scored.append(memory.model_copy(update={"rerank_score": round(rerank_score, 6)}))

    return sorted(
        scored,
        key=lambda memory: (
            -(memory.rerank_score or 0.0),
            -(memory.tick or -1),
            -(memory.similarity_score or 0.0),
            memory.raw_text,
            memory.id or "",
        ),
    )[:final_limit]


def score_relationship(relationship: Relationship) -> float:
    """Compute a transparent retrieval score for one directed relationship edge."""

    return round(
        relationship.trust
        + relationship.admiration
        + relationship.familiarity
        + relationship.attraction
        + relationship.obligation
        + (relationship.dependency * 0.5)
        - relationship.resentment
        - relationship.fear,
        6,
    )


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """Return cosine similarity for two same-length vectors, guarding zero norms."""

    if len(left) != len(right) or not left:
        return 0.0
    numerator = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = sqrt(sum(value * value for value in left))
    right_norm = sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return numerator / (left_norm * right_norm)
