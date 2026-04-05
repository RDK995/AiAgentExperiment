"""Integration tests for runtime wiring of the memory pipeline."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import create_engine, event as sqlalchemy_event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.enums import AgentSex, GoalSource, GoalStatus, GoalType, StageOfLife
from app.db.models import EpisodicMemory, MemoryEmbedding
from app.db.repositories import (
    AgentCreateParams,
    AgentRepository,
    EpisodicMemoryCreateParams,
    GoalCreateParams,
    MemoryRepository,
    RelationshipCreateParams,
)
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import AgentState, TerrainType, TileState, WorldState, build_initial_world_state
from app.memory.embeddings import DeterministicHashEmbeddingProvider
from app.schemas.event import EventType
from app.schemas.reflection import ReflectionContext, ReflectionResult


@dataclass(slots=True)
class SpyReflectionWorkflow:
    """Capture slow-loop contexts while returning a valid no-op reflection result."""

    calls: list[ReflectionContext] = field(default_factory=list)

    def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
        self.calls.append(context)
        return ReflectionResult(
            goals=["Maintain daily routine"],
            beliefs=[],
            memory_entries=[],
            planner_hints=[],
        )


def test_runtime_event_bus_routes_social_events_through_memory_pipeline() -> None:
    """Runtime-emitted important events should update memories, beliefs, and summary queues."""

    async def run_test() -> None:
        runtime = SimulationRuntime(
            initial_state=build_initial_world_state(width=4, height=3, initial_agent_count=2),
            tick_interval_seconds=60.0,
        )

        runtime._world_state.agents[1].hunger = 98.0

        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=2,
            location_y=1,
            payload={"item_type": "berries", "target_was_starving": True},
        )

        giver = runtime._world_state.agent_by_id("agent-1")
        receiver = runtime._world_state.agent_by_id("agent-2")

        assert giver is not None and receiver is not None
        assert giver.memories[-1] == "Gave berries to agent-2."
        assert receiver.memories[-1] == "agent-1 gave me berries."
        assert "agent:agent-1:is_generous:yes" in receiver.beliefs
        assert [candidate.text for candidate in receiver.daily_summary_candidates] == [
            "agent-1 gave me berries."
        ]

    asyncio.run(run_test())


def test_runtime_memory_pipeline_persists_embeddings_when_provider_is_enabled() -> None:
    """Live runtime event fan-out should persist memory embeddings when an embedding provider is configured."""

    async def run_test() -> None:
        import_models()
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

        @sqlalchemy_event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        @contextmanager
        def session_scope():
            session: Session = session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        bootstrap = session_factory()
        repository = AgentRepository(bootstrap)
        actor = repository.create_agent_bundle(
            AgentCreateParams(
                name="A",
                sex=AgentSex.FEMALE,
                birth_tick=0,
                current_tile_x=1,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
            )
        )
        target = repository.create_agent_bundle(
            AgentCreateParams(
                name="B",
                sex=AgentSex.MALE,
                birth_tick=0,
                current_tile_x=2,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
            )
        )
        bootstrap.commit()
        bootstrap.close()

        runtime = SimulationRuntime(
            initial_state=WorldState(
                width=4,
                height=3,
                day_index=100,
                tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
                agents=[
                    AgentState(agent_id="agent-1", name="A", x=1, y=1),
                    AgentState(agent_id="agent-2", name="B", x=2, y=1, hunger=98.0),
                ],
            ),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: {
                "agent-1": actor.id,
                "agent-2": target.id,
            }.get(agent_id),
            memory_embedding_provider=DeterministicHashEmbeddingProvider(),
        )

        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=1,
            location_y=1,
            payload={"item_type": "berries", "target_was_starving": True},
        )

        with session_scope() as session:
            memories = session.scalars(select(EpisodicMemory)).all()
            embeddings = session.scalars(select(MemoryEmbedding)).all()

        assert len(memories) == 2
        assert len(embeddings) == 2
        assert all(len(embedding.embedding) == 1536 for embedding in embeddings)

        engine.dispose()

    asyncio.run(run_test())


def test_runtime_memory_summary_prefers_daily_summary_candidates() -> None:
    """Runtime summarization should surface queued high-salience memory candidates ahead of raw recency noise."""

    async def run_test() -> None:
        runtime = SimulationRuntime(
            initial_state=build_initial_world_state(width=4, height=3, initial_agent_count=2),
            tick_interval_seconds=60.0,
        )

        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=2,
            location_y=1,
            payload={"item_type": "berries", "target_was_starving": True},
        )
        runtime._world_state.agents[1].memories.extend(["Slept well.", "Walked the path."])

        summary = await runtime.summarize_memories("agent-2")

        assert summary.summary.startswith("agent-1 gave me berries.")
        assert summary.memory_count == len(runtime._world_state.agents[1].memories)

    asyncio.run(run_test())


def test_runtime_exposes_daily_summary_candidates_per_agent() -> None:
    """Runtime should expose the queued daily-summary candidates in salience order."""

    async def run_test() -> None:
        runtime = SimulationRuntime(
            initial_state=build_initial_world_state(width=4, height=3, initial_agent_count=2),
            tick_interval_seconds=60.0,
        )

        await runtime.emit_simulation_event(
            EventType.CROP_FAILED,
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=2,
            location_y=1,
            payload={},
        )
        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=2,
            location_y=1,
            payload={"item_type": "berries", "target_was_starving": True},
        )

        candidates = await runtime.get_daily_summary_candidates("agent-2")

        assert candidates.agent_id == "agent-2"
        assert candidates.day_index == runtime._world_state.day_index
        assert [candidate.text for candidate in candidates.candidates] == [
            "A nearby crop failed.",
            "agent-1 gave me berries.",
        ]

    asyncio.run(run_test())


def test_runtime_day_rollover_expires_previous_day_summary_candidates() -> None:
    """Real day rollover should drop stale previous-day summary candidates before slow-loop reflection."""

    async def run_test() -> None:
        world = build_initial_world_state(width=4, height=3, initial_agent_count=2)
        rollover_time = datetime(2000, 1, 1, 23, 59, tzinfo=timezone.utc)
        world.current_time = rollover_time
        world.day_index = rollover_time.toordinal()

        runtime = SimulationRuntime(
            initial_state=world,
            tick_interval_seconds=120.0,
        )
        workflow = SpyReflectionWorkflow()
        runtime._slow_loop_service._reflection_workflow = workflow
        runtime._world_state.agents[1].hunger = 98.0

        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            location_x=2,
            location_y=1,
            payload={"item_type": "berries", "target_was_starving": True},
        )
        runtime._world_state.agents[1].memories.extend(["Walked the path.", "Slept well."])

        await runtime.step_once()

        receiver_context = next(context for context in workflow.calls if context.agent_id == "agent-2")
        receiver = runtime._world_state.agent_by_id("agent-2")
        assert receiver_context.trigger_reasons == [
            "day_rollover",
            "major_gift",
            "severe_hunger_or_injury",
        ]
        assert receiver_context.recent_events[:3] == [
            "Ate a meal.",
            "Slept well.",
            "Walked the path.",
        ]
        assert receiver is not None
        assert receiver.daily_summary_day_index == runtime._world_state.day_index
        assert receiver.daily_summary_candidates == []
        assert receiver_context.recent_events[-1] == "agent-1 gave me berries."

    asyncio.run(run_test())


def test_runtime_force_reflect_uses_retrieval_context_from_persistence() -> None:
    """Live runtime reflection should prepare context via the retrieval pipeline when persistence is available."""

    async def run_test() -> None:
        import_models()
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

        @sqlalchemy_event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        @contextmanager
        def session_scope():
            session: Session = session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        bootstrap = session_factory()
        repository = AgentRepository(bootstrap)
        actor = repository.create_agent_bundle(
            AgentCreateParams(
                name="A",
                sex=AgentSex.FEMALE,
                birth_tick=0,
                current_tile_x=1,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
                biography_summary="A keeps a careful village journal.",
            )
        )
        related = repository.create_agent_bundle(
            AgentCreateParams(
                name="B",
                sex=AgentSex.MALE,
                birth_tick=0,
                current_tile_x=2,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
            )
        )
        repository.create_goal(
            GoalCreateParams(
                agent_id=actor.id,
                goal_type=GoalType.WEALTH,
                title="Store grain before winter",
                priority=2.5,
                horizon_days=4,
                status=GoalStatus.ACTIVE,
                source=GoalSource.REFLECTION,
                created_tick=10,
                updated_tick=10,
            )
        )
        repository.create_relationship(
            RelationshipCreateParams(
                source_agent_id=actor.id,
                target_agent_id=related.id,
                trust=0.8,
                admiration=0.4,
                familiarity=0.3,
                last_interaction_tick=8,
            )
        )
        bootstrap.commit()
        bootstrap.close()

        runtime = SimulationRuntime(
            initial_state=WorldState(
                width=4,
                height=3,
                day_index=100,
                tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
                agents=[
                    AgentState(agent_id="agent-1", name="A", x=1, y=1),
                    AgentState(agent_id="agent-2", name="B", x=2, y=1),
                ],
            ),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: {
                "agent-1": actor.id,
                "agent-2": related.id,
            }.get(agent_id),
        )
        workflow = SpyReflectionWorkflow()
        runtime._slow_loop_service._reflection_workflow = workflow

        await runtime.force_reflect("agent-1")

        assert workflow.calls
        context = workflow.calls[0]
        assert context.autobiography == "A keeps a careful village journal."
        assert context.goals == ["Store grain before winter"]
        assert context.relationships == [str(related.id)]

        engine.dispose()

    asyncio.run(run_test())


def test_runtime_force_reflect_caps_retrieved_memory_context_for_reflection() -> None:
    """Live reflection preparation should keep retrieved memory context compact."""

    async def run_test() -> None:
        import_models()
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

        @sqlalchemy_event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        @contextmanager
        def session_scope():
            session: Session = session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        bootstrap = session_factory()
        agent_repository = AgentRepository(bootstrap)
        memory_repository = MemoryRepository(bootstrap)
        actor = agent_repository.create_agent_bundle(
            AgentCreateParams(
                name="A",
                sex=AgentSex.FEMALE,
                birth_tick=0,
                current_tile_x=1,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
                biography_summary="A keeps a careful village journal.",
            )
        )
        for tick in range(1, 18):
            memory_repository.create_memory(
                EpisodicMemoryCreateParams(
                    agent_id=actor.id,
                    tick=tick,
                    event_type="memory",
                    raw_text=f"persistent-memory-{tick}",
                    valence=0.0,
                    salience=min(1.0, 0.3 + tick * 0.02),
                )
            )
        bootstrap.commit()
        bootstrap.close()

        runtime = SimulationRuntime(
            initial_state=WorldState(
                width=4,
                height=3,
                day_index=100,
                tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
                agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1)],
            ),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: actor.id if agent_id == "agent-1" else None,
        )
        workflow = SpyReflectionWorkflow()
        runtime._slow_loop_service._reflection_workflow = workflow

        await runtime.force_reflect("agent-1")

        assert workflow.calls
        context = workflow.calls[0]
        assert len(context.recent_events) == 8
        assert context.recent_events[0] == "persistent-memory-17"
        assert context.recent_events[-1] == "persistent-memory-10"

        engine.dispose()

    asyncio.run(run_test())


def test_runtime_prepare_dialogue_context_uses_shared_retrieval_pipeline() -> None:
    """Speaking context should come from the same authoritative retrieval pipeline as reflection."""

    async def run_test() -> None:
        import_models()
        engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

        @sqlalchemy_event.listens_for(engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        Base.metadata.create_all(engine)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        @contextmanager
        def session_scope():
            session: Session = session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        bootstrap = session_factory()
        agent_repository = AgentRepository(bootstrap)
        memory_repository = MemoryRepository(bootstrap)
        actor = agent_repository.create_agent_bundle(
            AgentCreateParams(
                name="A",
                sex=AgentSex.FEMALE,
                birth_tick=0,
                current_tile_x=1,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
                biography_summary="A keeps a careful village journal.",
            )
        )
        related = agent_repository.create_agent_bundle(
            AgentCreateParams(
                name="B",
                sex=AgentSex.MALE,
                birth_tick=0,
                current_tile_x=2,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
            )
        )
        agent_repository.create_goal(
            GoalCreateParams(
                agent_id=actor.id,
                goal_type=GoalType.WEALTH,
                title="Store grain before winter",
                priority=3.0,
                horizon_days=5,
                status=GoalStatus.ACTIVE,
                source=GoalSource.REFLECTION,
                created_tick=10,
                updated_tick=10,
            )
        )
        agent_repository.create_relationship(
            RelationshipCreateParams(
                source_agent_id=actor.id,
                target_agent_id=related.id,
                trust=0.9,
                admiration=0.6,
                familiarity=0.8,
                attraction=0.2,
                obligation=0.4,
                resentment=0.0,
                fear=0.0,
                dependency=0.1,
                last_interaction_tick=21,
            )
        )
        for tick in range(1, 5):
            memory_repository.create_memory(
                EpisodicMemoryCreateParams(
                    agent_id=actor.id,
                    tick=tick,
                    event_type="memory",
                    raw_text=f"persistent-memory-{tick}",
                    valence=0.1,
                    salience=min(1.0, 0.4 + tick * 0.1),
                )
            )
        bootstrap.commit()
        bootstrap.close()

        runtime = SimulationRuntime(
            initial_state=WorldState(
                width=4,
                height=3,
                day_index=100,
                tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
                agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1)],
            ),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: actor.id if agent_id == "agent-1" else None,
        )

        context = await runtime.prepare_dialogue_context("agent-1", "winter grain planning")

        assert context.agent_id == "agent-1"
        assert context.topic_text == "winter grain planning"
        assert context.summary == "A keeps a careful village journal."
        assert context.goals == ["Store grain before winter"]
        assert context.relationships == [str(related.id)]
        assert context.memories == [
            "persistent-memory-4",
            "persistent-memory-3",
            "persistent-memory-2",
            "persistent-memory-1",
        ]
        assert "topic=winter grain planning" in context.prompt
        assert "Store grain before winter" in context.prompt
        assert str(related.id) in context.prompt

        engine.dispose()

    asyncio.run(run_test())
