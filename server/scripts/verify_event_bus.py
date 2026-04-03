"""Manual verification script for the authoritative backend event bus."""

from __future__ import annotations

import argparse
import asyncio
from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid

from sqlalchemy import create_engine, event as sqlalchemy_event, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base, import_models
from app.db.models import WorldEvent
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import build_initial_world_state
from app.schemas.event import EventType


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser for manual event-bus verification."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default="event-bus-review-output.json",
        help="Path to write the verification JSON report.",
    )
    return parser


async def build_report() -> dict[str, object]:
    """Run a compact end-to-end verification against the authoritative runtime."""

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

    persistent_ids = {
        "agent-1": uuid.uuid4(),
        "agent-2": uuid.uuid4(),
    }
    runtime = SimulationRuntime(
        initial_state=build_initial_world_state(width=8, height=6, initial_agent_count=2),
        tick_interval_seconds=60.0,
        world_event_session_scope=session_scope,
        persistent_agent_id_resolver=lambda agent_id: persistent_ids.get(agent_id),
    )

    await runtime.emit_simulation_event(
        EventType.PROPOSAL_ACCEPTED,
        agent_id="agent-1",
        actor_ids=["agent-1"],
        target_ids=["agent-2"],
        payload={"ring": "woven_grass"},
        source_module="manual-check",
    )
    await runtime.emit_simulation_event(
        EventType.GIFT_GIVEN,
        agent_id="agent-1",
        actor_ids=["agent-1"],
        target_ids=["agent-2"],
        payload={"item_type": "berries"},
        source_module="manual-check",
    )
    await runtime.emit_simulation_event(
        EventType.INSULT_SPOKEN,
        agent_id="agent-2",
        actor_ids=["agent-2"],
        target_ids=["agent-1"],
        payload={"phrase": "lazy"},
        source_module="manual-check",
    )

    before_tick_metrics = await runtime.get_debug_metrics()
    await runtime.step_once()
    after_tick_metrics = await runtime.get_debug_metrics()
    replay = await runtime.get_replay_events(limit=20)
    recent_world_events = await runtime.get_recent_world_events(limit=20)
    agent_1 = await runtime.inspect_agent("agent-1")
    agent_2 = await runtime.inspect_agent("agent-2")

    with session_scope() as session:
        persisted = session.scalars(select(WorldEvent).order_by(WorldEvent.tick, WorldEvent.id)).all()

    replay_types = [event.event_type for event in replay.events]
    persisted_types = [event.event_type for event in persisted]
    world_event_types = [event.event_type for event in recent_world_events]
    checks = {
        "relationship_linked": agent_1.agent.partner_id == "agent-2" and agent_2.agent.partner_id == "agent-1",
        "memory_written_agent_1": "A gift changed hands." in agent_1.memories,
        "memory_written_agent_2": "A gift changed hands." in agent_2.memories,
        "telemetry_counted_proposal": after_tick_metrics.last_tick_event_type_counts.get("proposal_accepted", 0) >= 1,
        "telemetry_counted_gift": after_tick_metrics.last_tick_event_type_counts.get("gift_given", 0) >= 1,
        "telemetry_counted_insult": after_tick_metrics.last_tick_event_type_counts.get("insult_spoken", 0) >= 1,
        "replay_contains_social_events": {"proposal_accepted", "gift_given", "insult_spoken"} <= set(replay_types),
        "world_event_projection_contains_social_events": {"proposal_accepted", "gift_given", "insult_spoken"} <= set(world_event_types),
        "persistence_contains_social_events": {"proposal_accepted", "gift_given", "insult_spoken"} <= set(persisted_types),
    }

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "checks": checks,
        "before_tick_metrics": before_tick_metrics.model_dump(mode="json"),
        "after_tick_metrics": after_tick_metrics.model_dump(mode="json"),
        "agent_1": agent_1.model_dump(mode="json"),
        "agent_2": agent_2.model_dump(mode="json"),
        "replay_events": replay.model_dump(mode="json"),
        "recent_world_events": [event.model_dump(mode="json") for event in recent_world_events],
        "persisted_world_events": [
            {
                "tick": event.tick,
                "event_type": event.event_type,
                "actor_ids": [str(actor_id) for actor_id in event.actor_ids],
                "target_ids": [str(target_id) for target_id in event.target_ids],
                "location_x": event.location_x,
                "location_y": event.location_y,
                "payload": event.payload,
            }
            for event in persisted
        ],
    }

    engine.dispose()
    return report


def main() -> int:
    """Run the verification and write the report to disk."""

    parser = build_parser()
    args = parser.parse_args()
    report = asyncio.run(build_report())
    output_path = Path(args.output).resolve()
    output_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return 0 if all(report["checks"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
