"""High-value tests for the three-loop simulation architecture."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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
from app.engine.scheduler import ScheduledTask, TaskScheduler
from app.engine.sim_clock import SimTick, SimulationClock
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_loop import WorldLoop
from app.engine.world_state import AgentState, TerrainType, TileState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.schemas.api import SimulationSnapshot
from app.schemas.event import EventType, SimulationEvent
from app.schemas.reflection import ReflectionResult
from app.telemetry.metrics import TelemetryRecorder


def test_sim_clock_advances_and_detects_day_rollover() -> None:
    """The simulation clock should advance deterministically and flag day changes."""

    start = datetime(2000, 1, 1, 23, 59, tzinfo=timezone.utc)
    clock = SimulationClock(start_time=start, tick_interval=timedelta(minutes=2))

    tick = clock.advance()

    assert tick.tick == 1
    assert tick.at == datetime(2000, 1, 2, 0, 1, tzinfo=timezone.utc)
    assert tick.day_rolled_over is True


def test_world_loop_calls_subsystems_in_order() -> None:
    """The world loop should execute subsystem hooks in the expected authoritative order."""

    call_order: list[str] = []

    class FakeWorld:
        tick = 0
        current_time = datetime(2000, 1, 1, 6, 0, tzinfo=timezone.utc)
        day_index = current_time.toordinal()

        def update_weather(self, now: datetime) -> None:
            call_order.append("world.update_weather")

        def update_resources(self, now: datetime) -> None:
            call_order.append("world.update_resources")

        def update_crops(self, now: datetime) -> None:
            call_order.append("world.update_crops")

        def to_snapshot(self) -> SimulationSnapshot:
            raise AssertionError("Snapshot generation is not needed for this ordering test.")

    class FakeScheduler:
        def dispatch_due_tasks(self, now: datetime, event_bus: EventBus) -> None:
            call_order.append("scheduler.dispatch_due_tasks")

    class FakeAgentRuntime:
        def step_all(self, world: FakeWorld, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
            call_order.append("agent_runtime.step_all")
            return []

    class FakeTelemetry:
        def record_stage(self, stage_name: str) -> None:
            pass

        def flush_tick(self, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
            call_order.append("telemetry.flush_tick")
            return []

    clock = SimulationClock(
        start_time=datetime(2000, 1, 1, 6, 0, tzinfo=timezone.utc),
        tick_interval=timedelta(minutes=5),
    )
    world_loop = WorldLoop(
        world_state=FakeWorld(),
        sim_clock=clock,
        scheduler=FakeScheduler(),
        agent_runtime=FakeAgentRuntime(),
        telemetry=FakeTelemetry(),
        event_bus=EventBus(),
    )

    try:
        world_loop.tick_once()
    except AssertionError:
        pass

    assert call_order == [
        "world.update_weather",
        "world.update_resources",
        "world.update_crops",
        "scheduler.dispatch_due_tasks",
        "agent_runtime.step_all",
        "telemetry.flush_tick",
    ]


def test_agent_fast_loop_runs_expected_stages(simple_world: WorldState) -> None:
    """The fast loop should execute its stages in the designed order."""

    runtime, _, _, _ = _build_runtime_components(simple_world)
    tick = SimTick(
        tick=1,
        at=datetime(2000, 1, 1, 6, 1, tzinfo=timezone.utc),
        previous_day_index=1,
        day_index=1,
    )

    runtime.step_all(simple_world, tick, EventBus())

    assert runtime.last_step_traces[0].stage_order == [
        "perceive",
        "update_needs",
        "score_actions",
        "plan",
        "execute",
        "emit_events",
    ]


def test_repeated_plan_failure_triggers_slow_loop_eligibility() -> None:
    """Repeated plan failures should trigger the slow loop and produce planner hints."""

    world = WorldState(
        width=1,
        height=1,
        tiles=[TileState(x=0, y=0, terrain=TerrainType.PATH, walkable=True)],
        agents=[AgentState(agent_id="agent-1", name="Villager 1", x=0, y=0)],
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )
    agent_runtime, slow_loop, world_loop, _ = _build_runtime_components(world)

    for index in range(3):
        world_loop.tick_once()

    assert slow_loop.last_results[0].trigger_reasons == ["repeated_plan_failure"]
    assert "reflect_on_failures" in world.agents[0].pending_planner_hints


def test_day_rollover_triggers_slow_loop_eligibility(simple_world: WorldState) -> None:
    """Crossing a simulation day boundary should trigger the slow loop."""

    start_time = datetime(2000, 1, 1, 23, 59, tzinfo=timezone.utc)
    simple_world.current_time = start_time
    simple_world.day_index = start_time.toordinal()
    _, slow_loop, world_loop, _ = _build_runtime_components(
        simple_world,
        start_time=start_time,
        tick_interval=timedelta(minutes=2),
    )

    world_loop.tick_once()

    assert slow_loop.last_results[0].trigger_reasons == ["day_rollover"]


def test_reflection_output_is_validated_before_application(simple_world: WorldState) -> None:
    """Invalid reflection output should be rejected before mutating agent state."""

    class InvalidReflectionWorkflow(ReflectionWorkflow):
        def run(self, agent: AgentState, context) -> ReflectionResult:
            return ReflectionResult(
                goals=[""],
                beliefs=[""],
                memory_entries=[""],
                planner_hints=[""],
            )

    event_bus = EventBus()
    slow_loop = SlowLoopService(
        memory_retriever=MemoryRetriever(),
        autobiography_builder=AutobiographyBuilder(),
        reflection_workflow=InvalidReflectionWorkflow(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )
    tick = SimTick(
        tick=1,
        at=datetime(2000, 1, 2, 0, 1, tzinfo=timezone.utc),
        previous_day_index=1,
        day_index=2,
    )
    event_bus.emit(
        SimulationEvent(
            type=EventType.DAY_ROLLOVER,
            tick=tick.tick,
            sim_time=tick.at,
            payload={"day_index": tick.day_index},
        )
    )

    results = slow_loop.handle_post_fast_loop(simple_world, tick, event_bus)

    assert slow_loop.last_results[0].applied is False
    assert simple_world.agents[0].current_goal == "Maintain daily routine"
    assert simple_world.agents[0].beliefs == []
    assert simple_world.agents[0].memories == []


def test_social_milestone_event_triggers_slow_loop(simple_world: WorldState) -> None:
    """Event-driven social milestones should trigger the slow loop on the backend."""

    _, slow_loop, world_loop, _ = _build_runtime_components(simple_world)
    event_bus = world_loop._event_bus  # type: ignore[attr-defined]
    tick = SimTick(
        tick=1,
        at=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        previous_day_index=1,
        day_index=1,
    )
    event_bus.emit(
        SimulationEvent(
            type=EventType.SOCIAL_MILESTONE,
            tick=tick.tick,
            sim_time=tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "friendship"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, tick, event_bus)

    assert slow_loop.last_results[0].trigger_reasons == ["social_milestone"]
    assert slow_loop.last_results[0].applied is True


def test_scheduler_recurring_tasks_reschedule_after_dispatch() -> None:
    """Recurring scheduler tasks should re-enqueue themselves after firing."""

    event_bus = EventBus()
    scheduler = TaskScheduler()
    dispatched_at: list[datetime] = []

    def callback(now: datetime, bus: EventBus) -> None:
        dispatched_at.append(now)

    start = datetime(2000, 1, 1, 6, 0, tzinfo=timezone.utc)
    scheduler.schedule(
        ScheduledTask(
            due_at=start,
            callback=callback,
            interval=timedelta(minutes=5),
            task_id="recurring-weather-check",
        )
    )

    scheduler.dispatch_due_tasks(start, event_bus)

    assert dispatched_at == [start]
    assert scheduler.pending_task_ids() == ["recurring-weather-check"]


def test_planner_hints_are_consumed_after_guiding_action(simple_world: WorldState) -> None:
    """Planner hints should influence fast-loop choice but not persist forever."""

    simple_world.agents[0].pending_planner_hints = ["rest_soon"]
    simple_world.agents[0].fatigue = 80.0
    runtime, _, _, _ = _build_runtime_components(simple_world)
    tick = SimTick(
        tick=1,
        at=datetime(2000, 1, 1, 6, 1, tzinfo=timezone.utc),
        previous_day_index=1,
        day_index=1,
    )

    runtime.step_all(simple_world, tick, EventBus())

    trace = runtime.last_step_traces[0]
    assert trace.selected_action == "rest"
    assert trace.planner_hints_before == ["rest_soon"]
    assert trace.planner_hints_after == []


def test_runtime_external_event_path_and_debug_state(simple_world: WorldState) -> None:
    """Runtime should accept external events and expose loop/debug state."""

    import asyncio

    async def run_test() -> None:
        runtime = SimulationRuntime(initial_state=simple_world, tick_interval_seconds=60.0)

        await runtime.emit_simulation_event(
            EventType.MAJOR_LIFE_EVENT,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "bereavement"},
        )
        await runtime.step_once()
        debug_state = await runtime.get_debug_state()

        assert debug_state["tick"] == 1
        assert debug_state["last_fast_loop_traces"][0]["stage_order"] == [
            "perceive",
            "update_needs",
            "score_actions",
            "plan",
            "execute",
            "emit_events",
        ]
        assert debug_state["last_slow_loop_results"][0]["trigger_reasons"] == ["major_life_event"]
        assert debug_state["last_tick_telemetry"]["event_types"]

    asyncio.run(run_test())


def _build_runtime_components(
    world: WorldState,
    start_time: datetime | None = None,
    tick_interval: timedelta = timedelta(minutes=5),
) -> tuple[AgentRuntime, SlowLoopService, WorldLoop, SimulationClock]:
    """Build a real three-loop stack for deterministic unit tests."""

    slow_loop = SlowLoopService(
        memory_retriever=MemoryRetriever(),
        autobiography_builder=AutobiographyBuilder(),
        reflection_workflow=ReflectionWorkflow(),
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )
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
