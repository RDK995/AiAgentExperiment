"""Manual verification script for retrieval-driven reflection integration."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
import json
from pathlib import Path

from sqlalchemy import create_engine, event as sqlalchemy_event
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
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import build_initial_world_state
from app.memory.embeddings import DeterministicHashEmbeddingProvider


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for retrieval/reflection verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="retrieval-reflection-review-output.json",
        help="Path to write the verification JSON report.",
    )
    return parser


async def build_report() -> dict[str, object]:
    """Run a compact end-to-end verification against retrieval-aware reflection."""

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

    embedding_provider = DeterministicHashEmbeddingProvider()
    with session_scope() as session:
        agent_repository = AgentRepository(session)
        memory_repository = MemoryRepository(session)

        persistent_agent_1 = agent_repository.create_agent_bundle(
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
        persistent_agent_2 = agent_repository.create_agent_bundle(
            AgentCreateParams(
                name="Bex",
                sex=AgentSex.MALE,
                birth_tick=0,
                current_tile_x=2,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
            )
        )
        agent_repository.create_goal(
            GoalCreateParams(
                agent_id=persistent_agent_1.id,
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
                source_agent_id=persistent_agent_1.id,
                target_agent_id=persistent_agent_2.id,
                trust=0.82,
                admiration=0.41,
                familiarity=0.35,
                attraction=0.12,
                obligation=0.20,
                last_interaction_tick=11,
            )
        )
        memory = memory_repository.create_memory(
            EpisodicMemoryCreateParams(
                agent_id=persistent_agent_1.id,
                tick=12,
                event_type="gift_given",
                raw_text="agent-2 gave me berries.",
                valence=0.7,
                salience=0.95,
            )
        )
        memory_repository.attach_embedding(
            MemoryEmbedding(
                memory_id=memory.id,
                agent_id=persistent_agent_1.id,
                embedding=embedding_provider.embed_text(memory.raw_text),
            )
        )

    runtime = SimulationRuntime(
        initial_state=build_initial_world_state(width=4, height=3, initial_agent_count=2),
        tick_interval_seconds=60.0,
        world_event_session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: {
            "agent-1": persistent_agent_1.id,
            "agent-2": persistent_agent_2.id,
        }.get(agent_id),
        memory_embedding_provider=embedding_provider,
    )

    runtime_agent = runtime._world_state.agent_by_id("agent-1")
    assert runtime_agent is not None
    retrieved_context = runtime._retrieval_service.retrieve_context(
        runtime_agent,
        query_text="agent-2 gave me berries.",
    )
    reflection_result = await runtime.force_reflect("agent-1")
    agent_inspect = await runtime.inspect_agent("agent-1")
    debug_state = await runtime.get_debug_state()

    checks = {
        "summary_from_biography": retrieved_context.summary == "Ari keeps careful records of village life.",
        "top_goal_retrieved": [goal.title for goal in retrieved_context.goals[:1]] == ["Store grain before winter"],
        "top_relationship_retrieved": [rel.related_agent_id for rel in retrieved_context.relationships[:1]] == [
            str(persistent_agent_2.id)
        ],
        "top_memory_retrieved": [memory.raw_text for memory in retrieved_context.memories[:1]] == [
            "agent-2 gave me berries."
        ],
        "reflection_applied": reflection_result.applied is True,
        "applied_goal_uses_retrieval": agent_inspect.agent.current_goal == "Store grain before winter",
        "support_network_belief_written": (
            f"agent:{persistent_agent_2.id}:is_part_of_my_support_network:yes" in agent_inspect.beliefs
        ),
        "retrieved_memory_written": "agent-2 gave me berries." in agent_inspect.memories,
    }

    return {
        "checks": checks,
        "retrieved_context": retrieved_context.model_dump(mode="json"),
        "force_reflect_result": reflection_result.model_dump(mode="json"),
        "agent_inspect": agent_inspect.model_dump(mode="json"),
        "debug_state": debug_state,
    }


def main() -> int:
    """Run verification and write a JSON report to disk."""

    parser = build_parser()
    args = parser.parse_args()
    report = asyncio.run(build_report())
    output_path = Path(args.output).resolve()
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
