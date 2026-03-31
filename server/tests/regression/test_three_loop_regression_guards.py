"""Compact regression tests for core three-loop simulation invariants."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.agents.executor import ActionExecutor
from app.agents.needs import NeedService
from app.agents.perception import PerceptionService
from app.agents.planner import ActionPlanner
from app.agents.runtime import AgentRuntime
from app.agents.utility_ai import UtilityAI
from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.reflection import ReflectionWorkflow
from app.cognition.reflection_graph import AutobiographyBuilder
from app.cognition.slow_loop import SlowLoopService
from app.cognition.validation import ReflectionValidator
from app.engine.event_bus import EventBus
from app.engine.scheduler import TaskScheduler
from app.engine.sim_clock import SimTick, SimulationClock
from app.engine.world_loop import WorldLoop
from app.engine.world_state import AgentState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.schemas.event import EventType, SimulationEvent
from app.schemas.reflection import ReflectionContext, ReflectionResult
from app.telemetry.metrics import TelemetryRecorder


@pytest.fixture
def regression_tick() -> SimTick:
    """A deterministic simulation tick for slow-loop regression tests."""

    return SimTick(
        tick=1,
        at=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        previous_day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )


def test_world_tick_order_regression_matches_authoritative_pipeline(
    simple_world: WorldState,
) -> None:
    """World ticks should keep the authoritative subsystem order stable."""

    telemetry = TelemetryRecorder()
    runtime = _build_agent_runtime()
    world_loop = WorldLoop(
        world_state=simple_world,
        sim_clock=SimulationClock(
            start_time=simple_world.current_time,
            tick_interval=timedelta(minutes=5),
        ),
        scheduler=TaskScheduler(),
        agent_runtime=runtime,
        telemetry=telemetry,
        event_bus=EventBus(),
    )

    world_loop.tick_once()

    assert telemetry.tick_history[-1].stage_order == [
        "clock.advance",
        "world.update_weather",
        "world.update_resources",
        "world.update_crops",
        "scheduler.dispatch_due_tasks",
        "agent_runtime.step_all",
    ]


def test_fast_loop_stage_order_regression_is_stable(simple_world: WorldState) -> None:
    """Fast-loop stage ordering should not drift as new behavior is added."""

    runtime = _build_agent_runtime()

    runtime.step_all(simple_world, _tick_at(hour=6, minute=5), EventBus())

    assert runtime.last_step_traces[0].stage_order == [
        "perceive",
        "update_needs",
        "score_actions",
        "plan",
        "execute",
        "emit_events",
    ]


@pytest.mark.parametrize(
    ("event_type", "expected_reason"),
    [
        (EventType.MAJOR_LIFE_EVENT, "major_life_event"),
        (EventType.SOCIAL_MILESTONE, "social_milestone"),
    ],
)
def test_event_driven_slow_loop_triggers_remain_wired(
    simple_world: WorldState,
    regression_tick: SimTick,
    event_type: EventType,
    expected_reason: str,
) -> None:
    """Major life and social events should continue to trigger slow loops."""

    slow_loop = _build_slow_loop_service()
    event_bus = EventBus()
    event_bus.emit(
        SimulationEvent(
            type=event_type,
            tick=regression_tick.tick,
            sim_time=regression_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"source": "regression-test"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, regression_tick, event_bus)

    assert slow_loop.last_results[0].trigger_reasons == [expected_reason]
    assert slow_loop.last_results[0].applied is True


def test_day_rollover_trigger_rule_regression_remains_wired(simple_world: WorldState) -> None:
    """Crossing midnight should continue to trigger the slow loop for agents."""

    start_time = datetime(2000, 1, 1, 23, 59, tzinfo=timezone.utc)
    simple_world.current_time = start_time
    simple_world.day_index = start_time.toordinal()
    _, slow_loop, world_loop, _ = _build_runtime_stack(
        simple_world,
        start_time=start_time,
        tick_interval=timedelta(minutes=2),
    )

    world_loop.tick_once()

    assert slow_loop.last_results[0].trigger_reasons == ["day_rollover"]
    assert slow_loop.last_results[0].applied is True


def test_repeated_plan_failure_trigger_rule_regression_remains_wired() -> None:
    """Repeated plan failures should continue to mark agents for slow-loop reflection."""

    world = WorldState(
        width=1,
        height=1,
        agents=[AgentState(agent_id="agent-1", name="Villager 1", x=0, y=0)],
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )
    _, slow_loop, world_loop, _ = _build_runtime_stack(world)

    for _ in range(3):
        world_loop.tick_once()

    assert world.agents[0].plan_failure_count == 3
    assert slow_loop.last_results[0].trigger_reasons == ["repeated_plan_failure"]
    assert slow_loop.last_results[0].applied is True


def test_invalid_reflection_outputs_remain_blocked_and_emit_no_hints(
    simple_world: WorldState,
    regression_tick: SimTick,
) -> None:
    """Invalid slow-loop outputs must stay blocked from mutating state."""

    class InvalidReflectionWorkflow(ReflectionWorkflow):
        def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
            return ReflectionResult(
                goals=[""],
                beliefs=["invalid"],
                memory_entries=["invalid"],
                planner_hints=["rest_soon"],
            )

    slow_loop = _build_slow_loop_service(reflection_workflow=InvalidReflectionWorkflow())
    event_bus = EventBus()
    event_bus.emit(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=regression_tick.tick,
            sim_time=regression_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "loss"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, regression_tick, event_bus)
    remaining_events = event_bus.drain()

    assert slow_loop.last_results[0].applied is False
    assert simple_world.agents[0].current_goal == "Maintain daily routine"
    assert simple_world.agents[0].beliefs == []
    assert simple_world.agents[0].memories == []
    assert simple_world.agents[0].pending_planner_hints == []
    assert all(event.type is not EventType.SLOW_LOOP_COMPLETED for event in remaining_events)


def test_validated_slow_loop_updates_state_and_gates_planner_hints(
    simple_world: WorldState,
    regression_tick: SimTick,
) -> None:
    """Planner hints and state updates should appear only after validation succeeds."""

    class ValidReflectionWorkflow(ReflectionWorkflow):
        def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
            return ReflectionResult(
                goals=["Find a better routine"],
                beliefs=["Resting earlier improves outcomes"],
                memory_entries=["Reflected on a major life event"],
                planner_hints=["rest_soon"],
            )

    slow_loop = _build_slow_loop_service(reflection_workflow=ValidReflectionWorkflow())
    event_bus = EventBus()
    event_bus.emit(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=regression_tick.tick,
            sim_time=regression_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "promotion"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, regression_tick, event_bus)
    remaining_events = event_bus.drain()

    assert slow_loop.last_results[0].applied is True
    assert simple_world.agents[0].current_goal == "Find a better routine"
    assert simple_world.agents[0].beliefs == ["Resting earlier improves outcomes"]
    assert simple_world.agents[0].memories[-1] == "Reflected on a major life event"
    assert simple_world.agents[0].pending_planner_hints == ["rest_soon"]
    assert any(event.type is EventType.SLOW_LOOP_COMPLETED for event in remaining_events)


def _build_agent_runtime(
    reflection_workflow: ReflectionWorkflow | None = None,
) -> AgentRuntime:
    """Build a real agent runtime with deterministic stub dependencies."""

    return AgentRuntime(
        perception_service=PerceptionService(),
        need_service=NeedService(),
        utility_ai=UtilityAI(),
        planner=ActionPlanner(),
        executor=ActionExecutor(),
        slow_loop_service=_build_slow_loop_service(reflection_workflow=reflection_workflow),
    )


def _build_slow_loop_service(
    reflection_workflow: ReflectionWorkflow | None = None,
) -> SlowLoopService:
    """Build a real slow-loop service with deterministic components."""

    return SlowLoopService(
        memory_retriever=MemoryRetriever(),
        autobiography_builder=AutobiographyBuilder(),
        reflection_workflow=reflection_workflow or ReflectionWorkflow(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )


def _build_runtime_stack(
    world: WorldState,
    start_time: datetime | None = None,
    tick_interval: timedelta = timedelta(minutes=5),
) -> tuple[AgentRuntime, SlowLoopService, WorldLoop, SimulationClock]:
    """Build a complete deterministic runtime stack for regression tests."""

    slow_loop = _build_slow_loop_service()
    agent_runtime = AgentRuntime(
        perception_service=PerceptionService(),
        need_service=NeedService(),
        utility_ai=UtilityAI(),
        planner=ActionPlanner(),
        executor=ActionExecutor(),
        slow_loop_service=slow_loop,
    )
    sim_clock = SimulationClock(start_time=start_time or world.current_time, tick_interval=tick_interval)
    world_loop = WorldLoop(
        world_state=world,
        sim_clock=sim_clock,
        scheduler=TaskScheduler(),
        agent_runtime=agent_runtime,
        telemetry=TelemetryRecorder(),
        event_bus=EventBus(),
    )
    return agent_runtime, slow_loop, world_loop, sim_clock


def _tick_at(hour: int, minute: int) -> SimTick:
    """Construct a deterministic tick for fast-loop regression tests."""

    return SimTick(
        tick=1,
        at=datetime(2000, 1, 1, hour, minute, tzinfo=timezone.utc),
        previous_day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )
