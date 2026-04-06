"""Focused tests for daily observability aggregation."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import uuid

from sqlalchemy import create_engine, event as sqlalchemy_event
from sqlalchemy.orm import Session, sessionmaker

from app.cognition.slow_loop import SlowLoopResult
from app.db.base import Base, import_models
from app.db.enums import AgentSex, StageOfLife
from app.db.repositories import AgentCreateParams, AgentRepository, RelationshipCreateParams
from app.engine.world_state import AgentState, ItemStackState, WorldState
from app.schemas.event import EventType, SimulationEvent
from app.telemetry.observability import DailyMetricsCollector


def test_daily_metrics_finalize_from_event_and_state_sources() -> None:
    """Finalization should merge event counters with authoritative world-state aggregations."""

    collector = DailyMetricsCollector()
    collector.start_day(100)
    world = WorldState(
        width=4,
        height=4,
        day_index=100,
        agents=[
            AgentState(
                agent_id="agent-1",
                name="A",
                x=1,
                y=1,
                stage_of_life=StageOfLife.ADULT,
                hunger=92.0,
                thirst=40.0,
                stress=30.0,
                household_id="house-1",
                partner_id="agent-2",
                inventory={"meal": 2, "water": 1, "wood": 1},
                home_inventory={"food": 1},
            ),
            AgentState(
                agent_id="agent-2",
                name="B",
                x=1,
                y=2,
                stage_of_life=StageOfLife.ADULT,
                hunger=48.0,
                thirst=20.0,
                stress=10.0,
                household_id="house-1",
                partner_id="agent-1",
                inventory={"crop": 2},
            ),
            AgentState(
                agent_id="child-1",
                name="Child",
                x=2,
                y=2,
                stage_of_life=StageOfLife.CHILD,
                hunger=20.0,
                thirst=10.0,
                stress=5.0,
                household_id="house-2",
            ),
            AgentState(
                agent_id="infant-1",
                name="Infant",
                x=2,
                y=1,
                stage_of_life=StageOfLife.INFANT,
                hunger=15.0,
                thirst=8.0,
                stress=2.0,
                household_id="house-2",
            ),
            AgentState(
                agent_id="elder-1",
                name="Elder",
                x=0,
                y=0,
                stage_of_life=StageOfLife.ADULT,
                alive=False,
                household_id="house-3",
            ),
        ],
        items=[
            ItemStackState(item_type="food", x=0, y=0, quantity=3),
            ItemStackState(item_type="water", x=0, y=1, quantity=2),
        ],
    )

    collector.observe_event(_event(EventType.CHILD_BORN, target_ids=["infant-1"]))
    collector.observe_event(_event(EventType.GIFT_GIVEN))
    collector.observe_event(_event(EventType.INSULT_SPOKEN))
    collector.observe_event(_event(EventType.TASK_COMPLETED, payload={"task": "cook_food"}))
    collector.observe_event(_event(EventType.TASK_COMPLETED, payload={"task": "harvest_crop"}))
    collector.observe_event(_event(EventType.AGENT_DIED, actor_ids=["elder-1"]))
    collector.observe_reflection_results(
        100,
        [
            SlowLoopResult(agent_id="agent-1", applied=True, retrieved_memory_count=6, token_cost=0.0),
            SlowLoopResult(agent_id="agent-2", applied=False, failure_stage="validate", retrieved_memory_count=2, token_cost=0.0),
        ],
    )

    snapshot = collector.finalize_day(
        world,
        day_index=100,
        finalized_at=datetime(2000, 1, 2, 0, 0, tzinfo=timezone.utc),
        next_day_index=101,
    )

    assert snapshot.day_index == 100
    assert snapshot.population.total_population == 4
    assert snapshot.population.births == 1
    assert snapshot.population.deaths == 1
    assert snapshot.population.infant_survival_rate == 1.0
    assert snapshot.population.age_distribution == {"adult": 2, "child": 1, "infant": 1}
    assert snapshot.welfare.average_hunger == 43.75
    assert snapshot.welfare.average_thirst == 19.5
    assert snapshot.welfare.average_stress == 11.75
    assert snapshot.welfare.starvation_count == 1
    assert snapshot.welfare.illness_count is None
    assert snapshot.social.active_bonds == 1
    assert snapshot.social.household_count == 2
    assert snapshot.social.mean_trust is None
    assert snapshot.social.conflict_events == 1
    assert snapshot.social.gifts_per_day == 1
    assert snapshot.economy.food_reserves == 8
    assert snapshot.economy.water_reserves == 3
    assert snapshot.economy.wood_stock == 1
    assert snapshot.economy.crop_yield == 1
    assert snapshot.economy.cooked_meals_per_day == 1
    assert snapshot.cognition.reflections_per_day == 2
    assert snapshot.cognition.average_memories_retrieved == 4.0
    assert snapshot.cognition.invalid_model_outputs == 1
    assert snapshot.cognition.mean_token_cost_per_day == 0.0


def test_daily_metrics_reset_after_finalization() -> None:
    """Finalization should reset counters so the next day starts cleanly."""

    collector = DailyMetricsCollector()
    collector.start_day(200)
    world = WorldState(width=2, height=2, day_index=200, agents=[AgentState(agent_id="agent-1", name="A", x=0, y=0)])

    collector.observe_event(_event(EventType.GIFT_GIVEN))
    first = collector.finalize_day(
        world,
        day_index=200,
        finalized_at=datetime(2000, 1, 3, 0, 0, tzinfo=timezone.utc),
        next_day_index=201,
    )
    second = collector.finalize_day(
        world,
        day_index=201,
        finalized_at=datetime(2000, 1, 4, 0, 0, tzinfo=timezone.utc),
        next_day_index=202,
    )

    assert first.social.gifts_per_day == 1
    assert second.social.gifts_per_day == 0
    assert collector.latest_snapshot() == second
    assert [snapshot.day_index for snapshot in collector.recent_snapshots(limit=5)] == [200, 201]


def test_daily_metrics_mean_trust_uses_persisted_relationship_rows_when_available() -> None:
    """Mean trust should come from the persisted relationship store when configured."""

    import_models()
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @sqlalchemy_event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine, expire_on_commit=False)()
    repository = AgentRepository(session)
    source = repository.create_agent_bundle(
        AgentCreateParams(
            name="Ari",
            sex=AgentSex.FEMALE,
            birth_tick=0,
            current_tile_x=0,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    target = repository.create_agent_bundle(
        AgentCreateParams(
            name="Bea",
            sex=AgentSex.MALE,
            birth_tick=0,
            current_tile_x=1,
            current_tile_y=0,
            stage_of_life=StageOfLife.ADULT,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=source.id,
            target_agent_id=target.id,
            trust=0.8,
        )
    )
    repository.create_relationship(
        RelationshipCreateParams(
            source_agent_id=target.id,
            target_agent_id=source.id,
            trust=0.4,
        )
    )
    session.commit()

    @contextmanager
    def session_scope():
        yield session

    collector = DailyMetricsCollector(session_scope=session_scope)
    collector.start_day(300)
    snapshot = collector.finalize_day(
        WorldState(width=1, height=1, day_index=300, agents=[]),
        day_index=300,
        finalized_at=datetime(2000, 1, 5, 0, 0, tzinfo=timezone.utc),
        next_day_index=301,
    )

    assert snapshot.social.mean_trust == 0.6
    session.close()
    engine.dispose()


def _event(
    event_type: EventType,
    *,
    actor_ids: list[str] | None = None,
    target_ids: list[str] | None = None,
    payload: dict[str, object] | None = None,
) -> SimulationEvent:
    return SimulationEvent(
        type=event_type,
        tick=1,
        sim_time=datetime(2000, 1, 1, 12, 0, tzinfo=timezone.utc),
        actor_ids=list(actor_ids or []),
        target_ids=list(target_ids or []),
        payload=payload or {},
    )
