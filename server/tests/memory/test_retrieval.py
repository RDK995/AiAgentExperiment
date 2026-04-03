"""Focused tests for the reflection/dialogue retrieval pipeline."""

from __future__ import annotations

from contextlib import contextmanager
import uuid

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.enums import AgentSex, GoalSource, GoalStatus, GoalType, StageOfLife
from app.db.models import MemoryEmbedding
from app.db.repositories import (
    AgentCreateParams,
    AgentRepository,
    EpisodicMemoryCreateParams,
    GoalCreateParams,
    MemoryRepository,
    RelationshipCreateParams,
)
from app.engine.world_state import AgentState
from app.memory.embeddings import DeterministicHashEmbeddingProvider
from app.memory.retrieval import RetrievalContextService, rerank_memories
from app.schemas.memory import RetrievedMemoryRecord


@pytest.fixture
def db_session() -> Session:
    """Create an isolated SQLite-backed ORM session for retrieval tests."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _runtime_agent(agent_id: str = "agent-1") -> AgentState:
    return AgentState(
        agent_id=agent_id,
        name="Ari",
        x=1,
        y=1,
        current_goal="Maintain daily routine",
        current_action="idle",
    )


def test_retrieval_prefers_persistent_biography_and_active_goals_in_priority_order(db_session: Session) -> None:
    """Persistent summary/goals should override runtime fallbacks and exclude completed goals."""

    agent_repository = AgentRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
            biography_summary="Ari keeps careful records of village life.",
        )
    )
    agent_repository.create_goal(
        GoalCreateParams(
            agent_id=persistent_agent.id,
            goal_type=GoalType.WEALTH,
            title="Store grain for winter",
            priority=3.0,
            horizon_days=5,
            status=GoalStatus.ACTIVE,
            source=GoalSource.REFLECTION,
            created_tick=10,
            updated_tick=10,
        )
    )
    agent_repository.create_goal(
        GoalCreateParams(
            agent_id=persistent_agent.id,
            goal_type=GoalType.SAFETY,
            title="Repair the storehouse roof",
            priority=2.0,
            horizon_days=2,
            status=GoalStatus.ACTIVE,
            source=GoalSource.REFLECTION,
            created_tick=11,
            updated_tick=11,
        )
    )
    agent_repository.create_goal(
        GoalCreateParams(
            agent_id=persistent_agent.id,
            goal_type=GoalType.FAMILY,
            title="Celebrate the harvest",
            priority=9.0,
            horizon_days=1,
            status=GoalStatus.COMPLETED,
            source=GoalSource.REFLECTION,
            created_tick=12,
            updated_tick=12,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
    )

    context = service.retrieve_context(_runtime_agent(), query_text="winter planning")

    assert context.summary == "Ari keeps careful records of village life."
    assert [goal.title for goal in context.goals] == [
        "Store grain for winter",
        "Repair the storehouse roof",
    ]
    assert all(goal.status == "active" for goal in context.goals)


def test_retrieval_falls_back_to_runtime_autobiography_when_persistent_summary_is_blank(db_session: Session) -> None:
    """Blank persistent biography summaries should fall back to runtime autobiography building."""

    agent_repository = AgentRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
            biography_summary="   ",
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    runtime_agent = _runtime_agent()
    runtime_agent.current_goal = "Keep the hearth lit"
    runtime_agent.memories = ["Shared soup at dusk."]
    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
    )

    context = service.retrieve_context(runtime_agent, query_text="hearth")

    assert context.summary == (
        "Ari is feeling steady and pursuing 'Keep the hearth lit'. "
        "Recent events: Shared soup at dusk."
    )
    assert [goal.title for goal in context.goals] == ["Keep the hearth lit"]


def test_retrieval_returns_top_ranked_outgoing_relationships_only_and_respects_limit(db_session: Session) -> None:
    """Relationship retrieval should rank the agent's outgoing edges and ignore unrelated incoming ones."""

    repository = AgentRepository(db_session)
    source = repository.create_agent_bundle(
        AgentCreateParams(
            name="Source",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=0,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    trusted = repository.create_agent_bundle(
        AgentCreateParams(
            name="Trusted",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    neutral = repository.create_agent_bundle(
        AgentCreateParams(
            name="Neutral",
            sex=AgentSex.INTERSEX,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    incoming_only = repository.create_agent_bundle(
        AgentCreateParams(
            name="Incoming",
            sex=AgentSex.INTERSEX,
            birth_tick=0,
            current_tile_x=3,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=source.id,
            target_agent_id=trusted.id,
            trust=0.8,
            admiration=0.4,
            familiarity=0.3,
            attraction=0.2,
            obligation=0.1,
            last_interaction_tick=20,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=source.id,
            target_agent_id=neutral.id,
            trust=0.2,
            familiarity=0.1,
            last_interaction_tick=21,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=incoming_only.id,
            target_agent_id=source.id,
            trust=1.0,
            admiration=1.0,
            familiarity=1.0,
            last_interaction_tick=99,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: source.id if agent_id == "agent-1" else None,
    )

    context = service.retrieve_context(_runtime_agent(), query_text="who do i trust", relationship_limit=1)

    assert len(context.relationships) == 1
    assert context.relationships[0].related_agent_id == str(trusted.id)
    assert context.relationships[0].score > 1.0


def test_retrieval_breaks_relationship_ties_deterministically_by_recency_then_target_id(db_session: Session) -> None:
    """Equal-score relationships should be ordered consistently across runs."""

    repository = AgentRepository(db_session)
    source = repository.create_agent_bundle(
        AgentCreateParams(
            name="Source",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=0,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    first = repository.create_agent_bundle(
        AgentCreateParams(
            name="First",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    second = repository.create_agent_bundle(
        AgentCreateParams(
            name="Second",
            sex=AgentSex.INTERSEX,
            birth_tick=0,
            current_tile_x=2,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    for target in (first, second):
        repository.create_relationship(
            RelationshipCreateParams(
                source_agent_id=source.id,
                target_agent_id=target.id,
                trust=0.5,
                admiration=0.3,
                familiarity=0.2,
                last_interaction_tick=10,
            )
        )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: source.id if agent_id == "agent-1" else None,
    )

    first_result = service.retrieve_context(_runtime_agent(), query_text="friends", relationship_limit=2)
    second_result = service.retrieve_context(_runtime_agent(), query_text="friends", relationship_limit=2)

    assert [relationship.related_agent_id for relationship in first_result.relationships] == [
        relationship.related_agent_id for relationship in second_result.relationships
    ]
    assert [relationship.related_agent_id for relationship in first_result.relationships] == sorted(
        [str(first.id), str(second.id)]
    )


def test_retrieval_recent_memories_exclude_archived_rows_and_respect_limit(db_session: Session) -> None:
    """Persistent recent-memory retrieval should skip archived rows and keep deterministic ordering."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=persistent_agent.id,
            tick=10,
            event_type="greeting",
            raw_text="Said hello by the gate.",
            valence=0.1,
            salience=0.2,
        )
    )
    memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=persistent_agent.id,
            tick=11,
            event_type="gift_given",
            raw_text="Received berries from agent-2.",
            valence=0.6,
            salience=0.8,
            archived=True,
        )
    )
    memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=persistent_agent.id,
            tick=12,
            event_type="child_born",
            raw_text="A child was born in the village.",
            valence=0.8,
            salience=0.95,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
    )

    context = service.retrieve_context(_runtime_agent(), query_text="village", recent_limit=2, similar_limit=0)

    assert [memory.raw_text for memory in context.memories] == [
        "A child was born in the village.",
        "Said hello by the gate.",
    ]


def test_blank_query_disables_similarity_search_and_returns_recent_memories_only(db_session: Session) -> None:
    """Blank queries should not invent similarity ranking even when embeddings exist."""

    provider = DeterministicHashEmbeddingProvider()
    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    memory = memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=persistent_agent.id,
            tick=20,
            event_type="gift_given",
            raw_text="agent-2 gave me berries by the well",
            valence=0.7,
            salience=0.9,
        )
    )
    memory_repository.attach_embedding(
        MemoryEmbedding(
            memory_id=memory.id,
            agent_id=persistent_agent.id,
            embedding=provider.embed_text(memory.raw_text),
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
        embedding_provider=provider,
    )

    context = service.retrieve_context(_runtime_agent(), query_text="   ", recent_limit=4, similar_limit=4)

    assert [memory.raw_text for memory in context.memories] == ["agent-2 gave me berries by the well"]
    assert context.memories[0].similarity_score is None


def test_similarity_search_uses_embeddings_and_favors_more_relevant_memory(db_session: Session) -> None:
    """Similarity retrieval should use stored embeddings when an embedding provider is configured."""

    provider = DeterministicHashEmbeddingProvider()
    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    matching = memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=persistent_agent.id,
            tick=20,
            event_type="gift_given",
            raw_text="agent-2 gave me berries by the well",
            valence=0.7,
            salience=0.9,
        )
    )
    different = memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=persistent_agent.id,
            tick=12,
            event_type="crop_failed",
            raw_text="the west field failed after heavy rain",
            valence=-0.8,
            salience=0.1,
        )
    )
    memory_repository.attach_embedding(
        MemoryEmbedding(
            memory_id=matching.id,
            agent_id=persistent_agent.id,
            embedding=provider.embed_text(matching.raw_text),
        )
    )
    memory_repository.attach_embedding(
        MemoryEmbedding(
            memory_id=different.id,
            agent_id=persistent_agent.id,
            embedding=provider.embed_text(different.raw_text),
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
        embedding_provider=provider,
    )

    context = service.retrieve_context(
        _runtime_agent(),
        query_text="agent-2 gave me berries by the well",
        recent_limit=2,
        similar_limit=2,
    )

    assert context.memories[0].raw_text == "agent-2 gave me berries by the well"
    assert context.memories[0].similarity_score is not None
    assert (context.memories[0].similarity_score or 0.0) > (context.memories[1].similarity_score or 0.0)


def test_similarity_search_failure_falls_back_cleanly_to_recent_memories(db_session: Session) -> None:
    """Embedding query failures should not invalidate retrieval context."""

    class ExplodingEmbeddingProvider:
        def embed_text(self, text: str) -> list[float] | None:
            raise RuntimeError("embedding backend unavailable")

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    memory_repository.create_memory(
        EpisodicMemoryCreateParams(
            agent_id=persistent_agent.id,
            tick=20,
            event_type="gift_given",
            raw_text="agent-2 gave me berries by the well",
            valence=0.7,
            salience=0.9,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
        embedding_provider=ExplodingEmbeddingProvider(),
    )

    context = service.retrieve_context(_runtime_agent(), query_text="berries", recent_limit=4, similar_limit=4)

    assert [memory.raw_text for memory in context.memories] == ["agent-2 gave me berries by the well"]
    assert context.memories[0].similarity_score is None


def test_rerank_memories_deduplicates_overlap_and_respects_final_cap() -> None:
    """Reranking should merge overlap, score deterministically, and cap the final context window."""

    overlapping_recent = RetrievedMemoryRecord(
        id=str(uuid.uuid4()),
        raw_text="agent-2 gave me berries",
        tick=10,
        salience=0.8,
        valence=0.6,
    )
    overlapping_similar = overlapping_recent.model_copy(update={"similarity_score": 0.95})
    extra_memories = [
        RetrievedMemoryRecord(
            id=str(uuid.uuid4()),
            raw_text=f"memory-{index}",
            tick=index,
            salience=0.4 + (index * 0.01),
            valence=0.0,
            similarity_score=0.1 if index % 2 else None,
        )
        for index in range(1, 8)
    ]

    reranked = rerank_memories(
        [overlapping_recent] + extra_memories[:4],
        [overlapping_similar] + extra_memories[4:],
        final_limit=5,
    )

    assert len(reranked) == 5
    assert reranked[0].raw_text == "agent-2 gave me berries"
    assert reranked[0].similarity_score == pytest.approx(0.95)
    assert reranked[0].rerank_score is not None
    assert sum(memory.raw_text == "agent-2 gave me berries" for memory in reranked) == 1


def test_rerank_memories_uses_deterministic_tie_breaking_and_zero_limit() -> None:
    """Tie cases and zero caps should produce stable deterministic results."""

    alpha = RetrievedMemoryRecord(
        id=str(uuid.uuid4()),
        raw_text="alpha",
        tick=5,
        salience=0.5,
        valence=0.0,
        similarity_score=0.2,
    )
    beta = RetrievedMemoryRecord(
        id=str(uuid.uuid4()),
        raw_text="beta",
        tick=5,
        salience=0.5,
        valence=0.0,
        similarity_score=0.2,
    )

    tied = rerank_memories([beta, alpha], [], final_limit=2)

    assert [memory.raw_text for memory in tied] == ["alpha", "beta"]
    assert rerank_memories([alpha, beta], [], final_limit=0) == []


def test_rerank_memories_can_favor_stronger_similarity_over_more_recent_lower_relevance() -> None:
    """The transparent reranking formula should let clearly stronger similarity win simple tradeoffs."""

    recent_but_weak = RetrievedMemoryRecord(
        id=str(uuid.uuid4()),
        raw_text="recent weak",
        tick=20,
        salience=0.2,
        valence=0.0,
        similarity_score=0.0,
    )
    older_but_strong = RetrievedMemoryRecord(
        id=str(uuid.uuid4()),
        raw_text="older strong",
        tick=10,
        salience=0.9,
        valence=0.0,
        similarity_score=0.95,
    )

    reranked = rerank_memories([recent_but_weak], [older_but_strong], final_limit=2)

    assert [memory.raw_text for memory in reranked] == ["older strong", "recent weak"]
    assert (reranked[0].rerank_score or 0.0) > (reranked[1].rerank_score or 0.0)


def test_retrieve_context_respects_final_memory_cap_across_runtime_and_persistent_sources(db_session: Session) -> None:
    """Context assembly should cap merged memories even when runtime and persistent sources both contribute."""

    agent_repository = AgentRepository(db_session)
    memory_repository = MemoryRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    for tick in range(1, 11):
        memory_repository.create_memory(
            EpisodicMemoryCreateParams(
                agent_id=persistent_agent.id,
                tick=tick,
                event_type="memory",
                raw_text=f"persistent-{tick}",
                valence=0.0,
                salience=min(1.0, 0.4 + (tick * 0.03)),
            )
        )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    runtime_agent = _runtime_agent()
    runtime_agent.memories = [f"runtime-{index}" for index in range(1, 11)]
    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
    )

    context = service.retrieve_context(runtime_agent, query_text="anything", final_memory_limit=5)

    assert len(context.memories) == 5


def test_retrieve_context_handles_empty_persistent_slice_cleanly(db_session: Session) -> None:
    """A persistent agent with no summary/goals/relationships/memories should still yield a valid context object."""

    agent_repository = AgentRepository(db_session)
    persistent_agent = agent_repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=1,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    db_session.commit()

    @contextmanager
    def session_scope():
        yield db_session

    runtime_agent = _runtime_agent()
    runtime_agent.current_goal = ""
    runtime_agent.memories = []
    service = RetrievalContextService(
        session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_agent.id if agent_id == "agent-1" else None,
    )

    context = service.retrieve_context(runtime_agent, query_text="nothing here")

    assert context.summary == "Ari is feeling steady and pursuing ''. Recent events: No notable events."
    assert context.goals == []
    assert context.relationships == []
    assert context.memories == []


def test_retrieval_falls_back_cleanly_without_persistence_or_embeddings() -> None:
    """Missing persistence or embeddings should still yield valid runtime-only context."""

    agent = _runtime_agent()
    agent.current_goal = "Keep the lanterns lit"
    agent.partner_id = "agent-2"
    agent.memories = ["Walked the village path."]

    context = RetrievalContextService().retrieve_context(agent, query_text="lanterns")

    assert "Keep the lanterns lit" in context.summary
    assert [goal.title for goal in context.goals] == ["Keep the lanterns lit"]
    assert [relationship.related_agent_id for relationship in context.relationships] == ["agent-2"]
    assert [memory.raw_text for memory in context.memories] == ["Walked the village path."]
