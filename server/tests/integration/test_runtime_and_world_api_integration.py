"""Phase 3 integration tests for backend runtime orchestration and FastAPI endpoints."""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event as sqlalchemy_event, select
from sqlalchemy.orm import Session, sessionmaker

from app.cognition.reflection import ReflectionWorkflow
from app.db.base import Base, import_models
from app.db.models import WorldEvent
from app.db.repositories import AgentCreateParams, AgentRepository, GoalCreateParams, RelationshipCreateParams
from app.db.enums import AgentSex, GoalSource, GoalStatus, GoalType, StageOfLife
from app.engine.scheduler import ScheduledTask
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import AgentState, ResourceNodeState, TerrainType, TileState, WorldState, build_initial_world_state
from app.schemas.agent import AgentStateSnapshot
from app.schemas.event import EventType, SimulationEvent
from app.schemas.api import (
    AgentInspectResponse,
    BeliefsResponse,
    EpisodesResponse,
    ForceReflectResponse,
    GoalsResponse,
    ReflectionRunsResponse,
    RelationshipsResponse,
    ReplayResponse,
    TimelineResponse,
)
from app.schemas.reflection import ReflectionContext, ReflectionOutput, ReflectionResult


def test_runtime_step_once_updates_authoritative_state_end_to_end() -> None:
    """A world tick should advance time and update authoritative world state end to end."""

    async def run_test() -> None:
        runtime = _build_runtime()

        before = await runtime.get_snapshot()
        after = await runtime.step_once()

        assert after.tick == before.tick + 1
        assert after.generated_at >= before.generated_at
        assert after.world.width == before.world.width
        assert after.world.height == before.world.height
        assert after.agents[0].needs.hunger > before.agents[0].needs.hunger
        assert runtime._world_state.weather != "clear" or runtime._world_state.resource_level != 100.0

    asyncio.run(run_test())


def test_scheduler_dispatch_and_telemetry_integrate_with_world_tick() -> None:
    """Scheduler callbacks, runtime stepping, and telemetry should integrate in one tick."""

    async def run_test() -> None:
        runtime = _build_runtime()
        scheduled_events: list[tuple[str, int]] = []
        due_at = runtime._world_state.current_time + timedelta(seconds=60)

        def callback(now, event_bus) -> None:
            scheduled_events.append(("fired", runtime._world_state.tick))
            event_bus.emit(
                SimulationEvent(
                    type=EventType.MAJOR_LIFE_EVENT,
                    tick=runtime._world_state.tick,
                    sim_time=now,
                    agent_id=runtime._world_state.agents[0].agent_id,
                    payload={"source": "scheduler"},
                )
            )

        runtime._scheduler.schedule(
            ScheduledTask(
                due_at=due_at,
                callback=callback,
                task_id="phase3-major-life-event",
            )
        )

        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert scheduled_events == [("fired", 1)]
        assert debug_state["pending_scheduler_tasks"] == []
        assert debug_state["last_slow_loop_results"][0]["trigger_reasons"] == ["major_life_event"]
        assert debug_state["last_tick_telemetry"]["stage_order"] == [
            "clock.advance",
            "world.update_weather",
            "world.update_resources",
            "world.update_crops",
            "scheduler.dispatch_due_tasks",
            "agent_runtime.step_all",
        ]
        assert "major_life_event" in debug_state["last_tick_telemetry"]["event_types"]
        assert "action_executed" in debug_state["last_tick_telemetry"]["event_types"]

    asyncio.run(run_test())


def test_runtime_external_event_is_consumed_by_slow_loop_on_next_tick() -> None:
    """Externally emitted authoritative events should trigger the slow loop on the next tick."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.MAJOR_LIFE_EVENT,
            agent_id=runtime._world_state.agents[0].agent_id,
            payload={"kind": "integration-test"},
        )
        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert debug_state["tick"] == 1
        assert debug_state["last_slow_loop_results"][0]["trigger_reasons"] == ["major_life_event"]
        assert debug_state["last_slow_loop_results"][0]["applied"] is True
        assert debug_state["last_fast_loop_traces"][0]["stage_order"] == [
            "perceive",
            "update_needs",
            "score_actions",
            "plan",
            "execute",
            "emit_events",
        ]

    asyncio.run(run_test())


def test_runtime_repeated_goal_failures_trigger_reflection_after_three_failures() -> None:
    """Plan-failure driven reflection should appear through the real runtime tick path."""

    async def run_test() -> None:
        world = WorldState(
            width=1,
            height=1,
            tiles=[TileState(x=0, y=0, terrain=TerrainType.PATH, walkable=True)],
            agents=[AgentState(agent_id="agent-1", name="Villager 1", x=0, y=0)],
            day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert debug_state["last_slow_loop_results"][0]["trigger_reasons"] == ["repeated_plan_failure"]
        assert "reflect_on_failures" in runtime._world_state.agents[0].pending_planner_hints

    asyncio.run(run_test())


def test_runtime_snapshot_exposes_current_action_for_survival_execution() -> None:
    """Authoritative snapshots should surface the action currently being executed."""

    async def run_test() -> None:
        world = WorldState(
            width=3,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(3) for x in range(3)],
            agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1, thirst=90.0)],
            resources=[ResourceNodeState(resource_type="water", x=1, y=1, quantity=2)],
            day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        snapshot = await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert snapshot.agents[0].current_action == "drink"
        assert debug_state["last_fast_loop_traces"][0]["selected_action"] == "drink"
        assert "agent_drank" in debug_state["last_fast_loop_traces"][0]["emitted_event_types"]

    asyncio.run(run_test())


def test_runtime_social_execution_uses_concrete_catalog_tasks_and_emits_social_event() -> None:
    """Runtime planning should expand social objectives into concrete catalog tasks and emit milestone events."""

    async def run_test() -> None:
        world = WorldState(
            width=3,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(3) for x in range(3)],
            agents=[
                AgentState(agent_id="agent-1", name="A", x=1, y=1, loneliness=90.0),
                AgentState(agent_id="agent-2", name="B", x=1, y=2),
            ],
            day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        snapshot = await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert snapshot.agents[0].current_action == "socialize"
        assert debug_state["last_fast_loop_traces"][0]["planned_tasks"] == ["greet", "talk"]
        assert "social_milestone" in debug_state["last_fast_loop_traces"][0]["emitted_event_types"]

    asyncio.run(run_test())


def test_runtime_day_rollover_finalizes_daily_metrics_and_exposes_them_through_debug_metrics() -> None:
    """Crossing a simulation day boundary should finalize the previous day's metrics snapshot."""

    async def run_test() -> None:
        rollover_time = datetime(2000, 1, 1, 23, 0, tzinfo=timezone.utc)
        world = WorldState(
            width=3,
            height=3,
            current_time=rollover_time,
            day_index=rollover_time.toordinal(),
            tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(3) for x in range(3)],
            agents=[
                AgentState(agent_id="agent-1", name="A", x=1, y=1, hunger=60.0, household_id="house-1"),
                AgentState(agent_id="agent-2", name="B", x=1, y=2, hunger=20.0, household_id="house-1"),
            ],
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=3600.0)

        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"item_type": "berries"},
            source_module="integration-test",
        )
        await runtime.step_once()
        metrics = await runtime.get_debug_metrics()

        assert metrics.latest_daily_metrics is not None
        assert metrics.latest_daily_metrics.day_index == rollover_time.toordinal()
        assert metrics.latest_daily_metrics.social.gifts_per_day == 1
        assert metrics.latest_daily_metrics.population.total_population == 2
        assert metrics.recent_daily_metrics[-1].day_index == rollover_time.toordinal()

    asyncio.run(run_test())


def test_runtime_bonded_pair_progresses_from_conception_to_birth_through_lifecycle() -> None:
    """Bonded adult partners should conceive and produce a child through the normal runtime tick path."""

    async def run_test() -> None:
        world = WorldState(
            width=4,
            height=4,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(4) for x in range(4)],
            agents=[
                AgentState(
                    agent_id="agent-1",
                    name="Ari",
                    x=1,
                    y=1,
                    sex=AgentSex.FEMALE,
                    partner_id="agent-2",
                    household_id="household-1",
                    family_orientation=0.6,
                ),
                AgentState(
                    agent_id="agent-2",
                    name="Bea",
                    x=2,
                    y=1,
                    sex=AgentSex.MALE,
                    partner_id="agent-1",
                    household_id="household-1",
                    family_orientation=0.7,
                ),
            ],
            day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)
        runtime._agent_runtime._lifecycle_service._reproduction_service._random_fn = lambda: 0.0

        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()

        event_types = [event.type for event in runtime._recent_events]
        child = runtime._world_state.agents[-1]

        assert EventType.PREGNANCY_STARTED in event_types
        assert EventType.CHILD_BORN in event_types
        assert len(runtime._world_state.agents) == 3
        assert child.stage_of_life is StageOfLife.INFANT
        assert child.parent_ids == ["agent-1", "agent-2"]
        assert child.household_id == "household-1"
        assert runtime._world_state.agents[0].has_infant_care_duty is True
        assert runtime._world_state.agents[1].has_infant_care_duty is True

    asyncio.run(run_test())


def test_runtime_social_window_can_progress_from_bond_attempt_to_birth_with_persistence() -> None:
    """Unbonded nearby adults with strong persisted relationships should bond, conceive, and give birth via runtime ticks."""

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
        persistent_a = repository.create_agent_bundle(
            AgentCreateParams(
                name="Ari",
                sex=AgentSex.FEMALE,
                birth_tick=0,
                current_tile_x=1,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
                household_id=None,
                trait_values={"family_orientation": 0.7},
            )
        )
        persistent_b = repository.create_agent_bundle(
            AgentCreateParams(
                name="Bea",
                sex=AgentSex.MALE,
                birth_tick=0,
                current_tile_x=2,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
                household_id=persistent_a.id,
                trait_values={"family_orientation": 0.65},
            )
        )
        persistent_a.household_id = persistent_a.id
        repository.create_relationship(
            RelationshipCreateParams(
                source_agent_id=persistent_a.id,
                target_agent_id=persistent_b.id,
                familiarity=0.82,
                trust=0.84,
                attraction=0.91,
                admiration=0.55,
                last_interaction_tick=6,
            )
        )
        repository.create_relationship(
            RelationshipCreateParams(
                source_agent_id=persistent_b.id,
                target_agent_id=persistent_a.id,
                familiarity=0.8,
                trust=0.8,
                attraction=0.88,
                admiration=0.5,
                last_interaction_tick=6,
            )
        )
        bootstrap.commit()
        bootstrap.close()

        world = WorldState(
            width=4,
            height=4,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(4) for x in range(4)],
            agents=[
                AgentState(
                    agent_id="agent-1",
                    name="Ari",
                    x=1,
                    y=1,
                    sex=AgentSex.FEMALE,
                    household_id="household-1",
                    family_orientation=0.7,
                ),
                AgentState(
                    agent_id="agent-2",
                    name="Bea",
                    x=2,
                    y=1,
                    sex=AgentSex.MALE,
                    household_id="household-1",
                    family_orientation=0.65,
                ),
            ],
            day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        )
        runtime = SimulationRuntime(
            initial_state=world,
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver={"agent-1": persistent_a.id, "agent-2": persistent_b.id}.get,
        )
        runtime._agent_runtime._lifecycle_service._reproduction_service._random_fn = lambda: 0.0

        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()

        event_types = [event.type for event in runtime._recent_events]
        child = runtime._world_state.agents[-1]

        with session_scope() as session:
            repository = AgentRepository(session)
            pair_bond = repository.get_pair_bond_between(persistent_a.id, persistent_b.id)

        assert EventType.PROPOSAL_MADE in event_types
        assert EventType.PROPOSAL_ACCEPTED in event_types
        assert EventType.PREGNANCY_STARTED in event_types
        assert EventType.CHILD_BORN in event_types
        assert runtime._world_state.agents[0].partner_id == "agent-2"
        assert runtime._world_state.agents[1].partner_id == "agent-1"
        assert child.stage_of_life is StageOfLife.INFANT
        assert child.parent_ids == ["agent-1", "agent-2"]
        assert pair_bond is not None

        engine.dispose()

    asyncio.run(run_test())


def test_runtime_does_not_emit_repeat_proposals_after_pair_is_already_bonded() -> None:
    """Once a pair is bonded, later ticks should not emit repeated proposal events for that same pair."""

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
        persistent_a = repository.create_agent_bundle(
            AgentCreateParams(
                name="Ari",
                sex=AgentSex.FEMALE,
                birth_tick=0,
                current_tile_x=1,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
                trait_values={"family_orientation": 0.7},
            )
        )
        persistent_b = repository.create_agent_bundle(
            AgentCreateParams(
                name="Bea",
                sex=AgentSex.MALE,
                birth_tick=0,
                current_tile_x=2,
                current_tile_y=1,
                stage_of_life=StageOfLife.ADULT,
                household_id=persistent_a.id,
                trait_values={"family_orientation": 0.65},
            )
        )
        persistent_a.household_id = persistent_a.id
        repository.create_relationship(
            RelationshipCreateParams(
                source_agent_id=persistent_a.id,
                target_agent_id=persistent_b.id,
                familiarity=0.82,
                trust=0.84,
                attraction=0.91,
                admiration=0.55,
                last_interaction_tick=6,
            )
        )
        repository.create_relationship(
            RelationshipCreateParams(
                source_agent_id=persistent_b.id,
                target_agent_id=persistent_a.id,
                familiarity=0.8,
                trust=0.8,
                attraction=0.88,
                admiration=0.5,
                last_interaction_tick=6,
            )
        )
        bootstrap.commit()
        bootstrap.close()

        world = WorldState(
            width=4,
            height=4,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.PATH, walkable=True) for y in range(4) for x in range(4)],
            agents=[
                AgentState(
                    agent_id="agent-1",
                    name="Ari",
                    x=1,
                    y=1,
                    sex=AgentSex.FEMALE,
                    household_id="household-1",
                    family_orientation=0.7,
                ),
                AgentState(
                    agent_id="agent-2",
                    name="Bea",
                    x=2,
                    y=1,
                    sex=AgentSex.MALE,
                    household_id="household-1",
                    family_orientation=0.65,
                ),
            ],
            day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        )
        runtime = SimulationRuntime(
            initial_state=world,
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver={"agent-1": persistent_a.id, "agent-2": persistent_b.id}.get,
        )
        runtime._agent_runtime._lifecycle_service._reproduction_service._random_fn = lambda: 1.0

        await runtime.step_once()
        await runtime.step_once()
        await runtime.step_once()

        event_types = [event.type for event in runtime._recent_events]

        assert event_types.count(EventType.PROPOSAL_MADE) == 1
        assert event_types.count(EventType.PROPOSAL_ACCEPTED) == 1
        assert runtime._world_state.agents[0].partner_id == "agent-2"
        assert runtime._world_state.agents[1].partner_id == "agent-1"

        engine.dispose()

    asyncio.run(run_test())


def test_runtime_agent_detail_services_return_typed_snapshots() -> None:
    """The runtime service should return rich typed agent snapshot DTOs, not raw dicts."""

    async def run_test() -> None:
        runtime = _build_runtime()

        collection = await runtime.get_agent_snapshots()
        single = await runtime.get_agent_snapshot("agent-1")

        assert collection
        assert all(isinstance(snapshot, AgentStateSnapshot) for snapshot in collection)
        assert isinstance(single, AgentStateSnapshot)
        assert single.agent_id == "agent-1"
        assert single.stage_of_life == "adult"

    asyncio.run(run_test())


def test_runtime_auxiliary_services_return_typed_endpoint_contracts() -> None:
    """The runtime should expose typed response models for the newer endpoint groups."""

    async def run_test() -> None:
        runtime = _build_runtime()

        reflection = await runtime.force_reflect("agent-1")
        relationships = await runtime.get_agent_relationships("agent-1")
        goals = await runtime.get_agent_goals("agent-1")
        timeline = await runtime.get_agent_timeline("agent-1")
        episodes = await runtime.get_memory_episodes("agent-1")
        beliefs = await runtime.get_memory_beliefs("agent-1")
        replay = await runtime.get_replay_events()
        inspect_agent = await runtime.inspect_agent("agent-1")

        assert isinstance(reflection, ForceReflectResponse)
        assert isinstance(relationships, RelationshipsResponse)
        assert isinstance(goals, GoalsResponse)
        assert isinstance(timeline, TimelineResponse)
        assert isinstance(episodes, EpisodesResponse)
        assert isinstance(beliefs, BeliefsResponse)
        assert isinstance(replay, ReplayResponse)
        assert isinstance(inspect_agent, AgentInspectResponse)
        assert reflection.agent_id == "agent-1"
        assert inspect_agent.agent.agent_id == "agent-1"

    asyncio.run(run_test())


def test_runtime_force_reflect_and_recent_reflections_expose_workflow_audit_fields() -> None:
    """Forced reflection should surface staged audit details through runtime responses."""

    async def run_test() -> None:
        runtime = _build_runtime()

        reflection = await runtime.force_reflect("agent-1")
        recent = await runtime.get_recent_reflections()

        assert isinstance(reflection, ForceReflectResponse)
        assert isinstance(recent, ReflectionRunsResponse)
        assert reflection.completed_stages[-2:] == ["persist_updates", "emit_planner_hints"]
        assert reflection.failure_stage is None
        assert reflection.validation_errors == []
        assert recent.reflections[-1].agent_id == "agent-1"
        assert recent.reflections[-1].completed_stages == reflection.completed_stages

    asyncio.run(run_test())


def test_runtime_force_reflect_surfaces_validation_failures_without_planner_hints() -> None:
    """Validation failures should be reported through force-reflect audit fields."""

    class InvalidReflectionWorkflow(ReflectionWorkflow):
        def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
            return ReflectionResult(
                goals=[""],
                beliefs=["invalid"],
                memory_entries=["invalid"],
                planner_hints=["rest_soon"],
            )

    async def run_test() -> None:
        runtime = _build_runtime()
        runtime._slow_loop_service._reflection_workflow = InvalidReflectionWorkflow()

        reflection = await runtime.force_reflect("agent-1")
        recent = await runtime.get_recent_reflections()

        assert reflection.applied is False
        assert reflection.planner_hints == []
        assert reflection.failure_stage == "validate"
        assert reflection.validation_errors
        assert recent.reflections[-1].failure_stage == "validate"
        assert recent.reflections[-1].applied is False

    asyncio.run(run_test())


def test_runtime_force_reflect_accepts_persistent_relationship_ids_in_reflection_output() -> None:
    """Persistence-backed relationship UUIDs should not cause reflection validation failure."""

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

        reflection = await runtime.force_reflect("agent-1")

        assert reflection.applied is True
        assert reflection.failure_stage is None
        assert reflection.validation_errors == []
        assert "keep_routine" in reflection.planner_hints
        assert any(
            belief == f"agent:{related.id}:is_part_of_my_support_network:yes"
            for belief in runtime._world_state.agent_by_id("agent-1").beliefs
        )

        engine.dispose()

    asyncio.run(run_test())


def test_runtime_force_reflect_accepts_existing_fast_loop_hints_from_valid_output() -> None:
    """Reflection output using eat_soon/drink_soon should remain valid and reach planner hints."""

    class HintLLMClient:
        def generate(self, prompt: str, **_: object) -> str:
            del prompt
            return ReflectionOutput(
                summary="Recover and replenish.",
                mood_delta={"morale": 0.5},
                belief_updates=[
                    {
                        "subject_type": "agent",
                        "subject_id": "agent-1",
                        "predicate": "can_improve_outcomes_by_adapting_routines",
                        "object_value": "yes",
                        "confidence_delta": 0.1,
                    }
                ],
                goal_updates=[
                    {
                        "action": "create",
                        "goal_type": "safety",
                        "title": "Recover before taking risks",
                        "priority": 0.8,
                        "horizon_days": 1,
                    }
                ],
                memory_candidates=[{"text": "I should recover.", "salience": 0.7, "valence": 0.1}],
                tomorrow_intentions=["eat_soon", "drink_soon"],
            ).model_dump_json()

    async def run_test() -> None:
        runtime = _build_runtime()
        runtime._slow_loop_service._reflection_workflow = ReflectionWorkflow(llm_client=HintLLMClient())

        reflection = await runtime.force_reflect("agent-1")

        assert reflection.applied is True
        assert reflection.failure_stage is None
        assert reflection.planner_hints == ["eat_soon", "drink_soon"]
        assert runtime._world_state.agent_by_id("agent-1").pending_planner_hints == ["eat_soon", "drink_soon"]

    asyncio.run(run_test())


def test_runtime_force_reflect_normalizes_high_level_planner_intentions() -> None:
    """High-level reflection intentions should be normalized before they reach authoritative agent state."""

    class HighLevelHintLLMClient:
        def generate(self, prompt: str, **_: object) -> str:
            del prompt
            return ReflectionOutput(
                summary="Invest in relationships and food security.",
                mood_delta={"morale": 0.5},
                belief_updates=[
                    {
                        "subject_type": "agent",
                        "subject_id": "agent-1",
                        "predicate": "can_improve_outcomes_by_adapting_routines",
                        "object_value": "yes",
                        "confidence_delta": 0.1,
                    }
                ],
                goal_updates=[
                    {
                        "action": "create",
                        "goal_type": "family",
                        "title": "Protect my household",
                        "priority": 0.8,
                        "horizon_days": 1,
                    }
                ],
                memory_candidates=[{"text": "I should prepare carefully.", "salience": 0.7, "valence": 0.1}],
                tomorrow_intentions=[
                    "spend_more_time_with_partner",
                    "avoid_bea_when_possible",
                    "prioritize_food_security",
                ],
            ).model_dump_json()

    async def run_test() -> None:
        runtime = _build_runtime()
        runtime._world_state.agents[1].name = "Bea"
        runtime._world_state.agents[0].partner_id = "agent-2"
        runtime._world_state.resources.append(ResourceNodeState(resource_type="berries", x=1, y=0, quantity=2))
        runtime._slow_loop_service._reflection_workflow = ReflectionWorkflow(llm_client=HighLevelHintLLMClient())

        reflection = await runtime.force_reflect("agent-1")

        assert reflection.applied is True
        assert reflection.planner_hints == [
            "visit_partner",
            "avoid_agent_agent-2",
            "prioritize_food_security",
        ]
        assert runtime._world_state.agent_by_id("agent-1").pending_planner_hints == [
            "visit_partner",
            "avoid_agent_agent-2",
            "prioritize_food_security",
        ]

    asyncio.run(run_test())


def test_runtime_spawn_food_creates_authoritative_item_stack() -> None:
    """Admin food spawning should populate authoritative world items for the engine modules."""

    async def run_test() -> None:
        runtime = _build_runtime()

        response = await runtime.spawn_food(tile_x=2, tile_y=2, quantity=3, item_type="berries")

        assert response.item_type == "berries"
        assert response.quantity == 3
        assert len(runtime._world_state.items) == 1
        assert runtime._world_state.items[0].item_type == "berries"
        assert runtime._world_state.items[0].quantity == 3

    asyncio.run(run_test())


def test_runtime_resource_targeting_moves_agent_toward_water_and_finishes_resource_drink_plan() -> None:
    """Perception, planning, and execution should form a targeted water-seeking loop."""

    async def run_test() -> None:
        world = WorldState(
            width=4,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
            agents=[AgentState(agent_id="agent-1", name="A", x=0, y=1, thirst=80.0)],
            resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=1)],
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        first = await runtime.step_once()
        second = await runtime.step_once()
        third = await runtime.step_once()
        fourth = await runtime.step_once()
        debug_state = await runtime.get_debug_state()
        recent_events = await runtime.get_recent_world_events(limit=20)

        assert first.agents[0].position.x == 1
        assert second.agents[0].position.x == 2
        assert third.agents[0].needs.thirst < second.agents[0].needs.thirst
        assert fourth.agents[0].needs.thirst < third.agents[0].needs.thirst
        assert runtime._world_state.resources == []
        assert debug_state["last_fast_loop_traces"][0]["selected_action"] == "drink"
        assert any(event.event_type == "task_progress" for event in recent_events)
        assert any(event.event_type == "task_completed" for event in recent_events)

    asyncio.run(run_test())


def test_runtime_debug_state_surfaces_perception_planning_execution_and_lifecycle_signals() -> None:
    """The runtime debug surface should expose the wired engine-module flow for one tick."""

    async def run_test() -> None:
        world = WorldState(
            width=4,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
            agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1, thirst=70.0, health=0.0)],
            resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=1)],
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        trace = debug_state["last_fast_loop_traces"][0]
        assert trace["perception_summary"]["nearby_water"] is True
        assert trace["top_action_candidates"][0]["action"] == "drink"
        assert trace["planned_tasks"] == ["move_to", "fetch_water", "drink"]
        assert "action_executed" in trace["emitted_event_types"]
        assert "action_executed" in debug_state["last_fast_loop_event_types"]
        assert "death" in debug_state["last_lifecycle_event_types"]
        assert "death" in debug_state["last_tick_telemetry"]["event_types"]

    asyncio.run(run_test())


def test_runtime_recent_world_events_expose_shared_transport_shape_for_engine_events() -> None:
    """Recent runtime events should be adapted into stable world-event DTOs with actor ids and payloads."""

    async def run_test() -> None:
        world = WorldState(
            width=4,
            height=3,
            tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(4)],
            agents=[AgentState(agent_id="agent-1", name="A", x=0, y=1, thirst=80.0)],
            resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=1)],
        )
        runtime = SimulationRuntime(initial_state=world, tick_interval_seconds=60.0)

        await runtime.step_once()
        recent_events = await runtime.get_recent_world_events(limit=10)

        assert recent_events
        assert all(event.event_id for event in recent_events)
        assert all(event.tick >= 1 for event in recent_events)
        assert any(event.event_type == "task_progress" for event in recent_events)
        assert any(event.event_type == "action_executed" for event in recent_events)

        action_event = next(event for event in recent_events if event.event_type == "action_executed")
        assert action_event.actor_ids == ["agent-1"]
        assert action_event.target_ids == []
        assert "action" in action_event.payload
        assert "position" in action_event.payload

    asyncio.run(run_test())


def test_runtime_event_bus_applies_relationship_listener_and_replay_projection() -> None:
    """Runtime-emitted social events should update authoritative state and reach replay/world-event surfaces."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.PROPOSAL_ACCEPTED,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"ring": "woven_grass"},
            source_module="integration-test",
        )

        assert runtime._world_state.agents[0].partner_id == "agent-2"
        assert runtime._world_state.agents[1].partner_id == "agent-1"

        await runtime.step_once()
        replay = await runtime.get_replay_events(limit=10)
        recent_events = await runtime.get_recent_world_events(limit=10)

        proposal_event = next(event for event in recent_events if event.event_type == "proposal_accepted")
        replay_event = next(event for event in replay.events if event.event_type == "proposal_accepted")

        assert proposal_event.actor_ids == ["agent-1"]
        assert proposal_event.target_ids == ["agent-2"]
        assert proposal_event.source_module == "integration-test"
        assert proposal_event.payload == {"ring": "woven_grass"}
        assert replay_event.agent_id == "agent-1"
        assert replay_event.payload == {"ring": "woven_grass"}

    asyncio.run(run_test())


def test_runtime_event_bus_projects_memories_and_telemetry_aggregates() -> None:
    """Important runtime events should update memories immediately and roll into telemetry aggregates."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.GIFT_GIVEN,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"item_type": "berries"},
            source_module="integration-test",
        )

        assert "Gave berries to agent-2." in runtime._world_state.agents[0].memories
        assert "agent-1 gave me berries." in runtime._world_state.agents[1].memories

        await runtime.step_once()
        metrics = await runtime.get_debug_metrics()

        assert metrics.last_tick_event_type_counts["gift_given"] == 1
        assert "gift_given" in metrics.last_tick_event_types

    asyncio.run(run_test())


def test_runtime_event_bus_fans_out_consumption_events_across_memory_replay_and_telemetry() -> None:
    """Consumption events should update memories immediately and remain visible in replay and telemetry."""

    async def run_test() -> None:
        runtime = _build_runtime()

        await runtime.emit_simulation_event(
            EventType.AGENT_ATE,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"action": "eat"},
            source_module="integration-test",
        )
        await runtime.emit_simulation_event(
            EventType.AGENT_DRANK,
            agent_id="agent-2",
            actor_ids=["agent-2"],
            payload={"action": "drink"},
            source_module="integration-test",
        )

        assert "Ate a meal." in runtime._world_state.agents[0].memories
        assert "Drank fresh water." in runtime._world_state.agents[1].memories

        await runtime.step_once()
        replay = await runtime.get_replay_events(limit=20)
        metrics = await runtime.get_debug_metrics()
        recent_events = await runtime.get_recent_world_events(limit=20)

        assert {"agent_ate", "agent_drank"} <= {event.event_type for event in replay.events}
        assert metrics.last_tick_event_type_counts["agent_ate"] == 1
        assert metrics.last_tick_event_type_counts["agent_drank"] == 1
        assert {"agent_ate", "agent_drank"} <= {event.event_type for event in recent_events}

    asyncio.run(run_test())


def test_runtime_event_bus_fans_out_lifecycle_domain_events_with_optional_persistence() -> None:
    """Lifecycle-style events should reach memory, telemetry, replay, and persistence listeners together."""

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

        actor_uuid = uuid.uuid4()
        child_uuid = uuid.uuid4()
        runtime = SimulationRuntime(
            initial_state=build_initial_world_state(width=8, height=6, initial_agent_count=2),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: {
                "agent-1": actor_uuid,
                "agent-2": child_uuid,
            }.get(agent_id),
        )

        await runtime.emit_simulation_event(
            EventType.CHILD_BORN,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"child_id": "agent-2"},
            source_module="integration-test",
        )
        await runtime.emit_simulation_event(
            EventType.AGENT_DIED,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            payload={"kind": "health_failure"},
            source_module="integration-test",
        )

        assert "agent-2 was born." in runtime._world_state.agents[0].memories
        assert "agent-1 died." in runtime._world_state.agents[0].memories

        await runtime.step_once()
        replay = await runtime.get_replay_events(limit=20)
        metrics = await runtime.get_debug_metrics()

        with session_scope() as session:
            persisted = session.scalars(select(WorldEvent).order_by(WorldEvent.tick, WorldEvent.id)).all()

        assert {"child_born", "agent_died"} <= {event.event_type for event in replay.events}
        assert metrics.last_tick_event_type_counts["child_born"] == 1
        assert metrics.last_tick_event_type_counts["agent_died"] == 1
        assert {"child_born", "agent_died"} <= {event.event_type for event in persisted}
        engine.dispose()

    asyncio.run(run_test())


def test_runtime_optional_world_event_persistence_listener_writes_to_repository() -> None:
    """Runtime should support an optional persistence listener without changing core loop ownership."""

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

        actor_uuid = uuid.uuid4()
        target_uuid = uuid.uuid4()
        runtime = SimulationRuntime(
            initial_state=build_initial_world_state(width=8, height=6, initial_agent_count=2),
            tick_interval_seconds=60.0,
            world_event_session_scope=session_scope,
            persistent_agent_id_resolver=lambda agent_id: {
                "agent-1": actor_uuid,
                "agent-2": target_uuid,
            }.get(agent_id),
        )

        await runtime.emit_simulation_event(
            EventType.PROPOSAL_ACCEPTED,
            agent_id="agent-1",
            actor_ids=["agent-1"],
            target_ids=["agent-2"],
            payload={"ring": "woven_grass"},
            source_module="integration-test",
        )

        with session_scope() as session:
            persisted = session.scalars(select(WorldEvent)).all()

        assert len(persisted) == 1
        assert persisted[0].event_type == "proposal_accepted"
        assert persisted[0].actor_ids == [actor_uuid]
        assert persisted[0].target_ids == [target_uuid]
        assert persisted[0].payload == {"ring": "woven_grass"}

        engine.dispose()

    asyncio.run(run_test())


def test_tick_and_run_endpoints_advance_authoritative_state_end_to_end(client: TestClient) -> None:
    """The FastAPI tick and run endpoints should mutate authoritative backend state."""

    initial_snapshot = client.get("/api/v1/world/snapshot").json()
    tick_snapshot = client.post("/api/v1/world/tick").json()
    run_snapshot = client.post("/api/v1/world/run", json={"ticks": 2}).json()
    final_state = client.get("/api/v1/world/state").json()

    assert tick_snapshot["tick"] == initial_snapshot["tick"] + 1
    assert run_snapshot["tick"] == tick_snapshot["tick"] + 2
    assert final_state["tick"] == run_snapshot["tick"]
    assert final_state["agents"][0]["needs"]["hunger"] > initial_snapshot["agents"][0]["needs"]["hunger"]
    assert final_state["agents"][0]["current_action"] == run_snapshot["agents"][0]["current_action"]


def test_snapshot_and_state_endpoints_reflect_same_authoritative_backend_state(
    client: TestClient,
) -> None:
    """State and snapshot endpoints should agree after authoritative backend changes."""

    client.post("/api/v1/world/tick")
    client.post("/api/v1/world/tick")

    snapshot = client.get("/api/v1/world/snapshot").json()
    state = client.get("/api/v1/world/state").json()

    assert snapshot["tick"] == 2
    assert state["tick"] == 2
    assert snapshot["world"] == state["world"]
    assert snapshot["agents"] == state["agents"]


def test_agent_detail_endpoints_return_richer_typed_snapshot_contracts(client: TestClient) -> None:
    """Agent detail endpoints should expose the richer backend-facing snapshot DTOs."""

    collection = client.get("/api/v1/world/agents")
    single = client.get("/api/v1/world/agents/agent-1")

    assert collection.status_code == 200
    assert single.status_code == 200

    collection_payload = collection.json()
    single_payload = single.json()

    assert len(collection_payload["agents"]) >= 1
    assert single_payload["agent_id"] == "agent-1"
    assert single_payload["stage_of_life"] == "adult"
    assert single_payload["tile_x"] >= 0
    assert single_payload["tile_y"] >= 0
    assert set(single_payload["needs"].keys()) == {
        "hunger",
        "thirst",
        "fatigue",
        "warmth",
        "health",
        "stress",
        "loneliness",
        "safety",
    }
    assert set(single_payload["mood"].keys()) == {"hope", "grief", "morale", "shame"}


def test_agent_detail_endpoint_returns_404_for_unknown_agent(client: TestClient) -> None:
    """Unknown agents should fail cleanly on the richer detail endpoint."""

    response = client.get("/api/v1/world/agents/unknown-agent")

    assert response.status_code == 404
    assert response.json() == {
        "error": "not_found",
        "message": "Unknown agent 'unknown-agent'.",
    }


def _build_runtime() -> SimulationRuntime:
    """Build a real simulation runtime with deterministic initial state."""

    initial_world: WorldState = build_initial_world_state(width=8, height=6, initial_agent_count=2)
    return SimulationRuntime(initial_state=initial_world, tick_interval_seconds=60.0)
