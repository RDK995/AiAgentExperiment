"""Phase 1 deterministic unit tests for the core three-loop backend."""

from __future__ import annotations

from dataclasses import dataclass
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
from app.engine.world_state import AgentState, TerrainType, TileState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.schemas.api import SimulationSnapshot
from app.schemas.event import EventType, SimulationEvent
from app.telemetry.metrics import TelemetryRecorder


@dataclass(slots=True)
class RecordingSlowLoopService:
    """Minimal slow-loop stub that records trigger eligibility without reflection."""

    last_seen_flags_by_agent: dict[str, set[str]] | None = None
    call_count: int = 0

    def handle_post_fast_loop(
        self,
        world: WorldState,
        tick: SimTick,
        event_bus: EventBus,
    ) -> list[SimulationEvent]:
        self.call_count += 1
        drained_events = event_bus.drain()
        for event in drained_events:
            if event.type is EventType.DAY_ROLLOVER:
                for agent in world.agents:
                    agent.slow_loop_trigger_flags.add("day_rollover")
            elif event.type is EventType.PLAN_FAILED and event.agent_id is not None:
                agent = world.agent_by_id(event.agent_id)
                if agent is not None and agent.plan_failure_count >= 3:
                    agent.slow_loop_trigger_flags.add("repeated_plan_failure")
        self.last_seen_flags_by_agent = {
            agent.agent_id: set(agent.slow_loop_trigger_flags) for agent in world.agents
        }
        for event in drained_events:
            event_bus.emit(event)
        return drained_events


class ExplodingReflectionWorkflow(ReflectionWorkflow):
    """Reflection stub that fails if a no-trigger fast-loop path invokes it."""

    def run(self, agent: AgentState, context) -> object:
        raise AssertionError("Fast-loop test unexpectedly required reflection work.")


@pytest.fixture
def single_tile_world() -> WorldState:
    """A one-tile world where wandering is always illegal and deterministic."""

    return WorldState(
        width=1,
        height=1,
        tiles=[TileState(x=0, y=0, terrain=TerrainType.PATH, walkable=True)],
        agents=[AgentState(agent_id="agent-1", name="Villager 1", x=0, y=0)],
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )


def test_sim_clock_advance_increments_tick_without_day_rollover() -> None:
    """The sim clock should advance deterministically within a day."""

    clock = SimulationClock(
        start_time=datetime(2000, 1, 1, 6, 0, tzinfo=timezone.utc),
        tick_interval=timedelta(minutes=5),
    )

    tick = clock.advance()

    assert tick.tick == 1
    assert tick.at == datetime(2000, 1, 1, 6, 5, tzinfo=timezone.utc)
    assert tick.day_rolled_over is False


def test_sim_clock_detects_day_rollover() -> None:
    """The sim clock should flag day rollovers when crossing midnight."""

    clock = SimulationClock(
        start_time=datetime(2000, 1, 1, 23, 59, tzinfo=timezone.utc),
        tick_interval=timedelta(minutes=2),
    )

    tick = clock.advance()

    assert tick.tick == 1
    assert tick.at == datetime(2000, 1, 2, 0, 1, tzinfo=timezone.utc)
    assert tick.day_rolled_over is True


def test_world_tick_loop_calls_subsystems_in_correct_order() -> None:
    """The world loop should preserve authoritative subsystem ordering."""

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
            raise AssertionError("Snapshot generation is not part of the ordering assertion.")

    class FakeScheduler:
        def dispatch_due_tasks(self, now: datetime, event_bus: EventBus) -> None:
            call_order.append("scheduler.dispatch_due_tasks")

    class FakeAgentRuntime:
        def step_all(self, world: FakeWorld, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
            call_order.append("agent_runtime.step_all")
            return []

    class FakeTelemetry:
        def record_stage(self, stage_name: str) -> None:
            if stage_name == "clock.advance":
                call_order.append("clock.advance")

        def flush_tick(self, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
            call_order.append("telemetry.flush_tick")
            return []

    world_loop = WorldLoop(
        world_state=FakeWorld(),
        sim_clock=SimulationClock(
            start_time=datetime(2000, 1, 1, 6, 0, tzinfo=timezone.utc),
            tick_interval=timedelta(minutes=5),
        ),
        scheduler=FakeScheduler(),
        agent_runtime=FakeAgentRuntime(),
        telemetry=FakeTelemetry(),
        event_bus=EventBus(),
    )

    with pytest.raises(AssertionError, match="Snapshot generation"):
        world_loop.tick_once()

    assert call_order == [
        "clock.advance",
        "world.update_weather",
        "world.update_resources",
        "world.update_crops",
        "scheduler.dispatch_due_tasks",
        "agent_runtime.step_all",
        "telemetry.flush_tick",
    ]


def test_agent_fast_loop_stages_run_in_correct_order(simple_world: WorldState) -> None:
    """The fast loop should run its deterministic stages in sequence."""

    runtime = _build_agent_runtime(RecordingSlowLoopService())

    runtime.step_all(simple_world, _tick_at(hour=6, minute=5), EventBus())

    assert runtime.last_step_traces[0].stage_order == [
        "perceive",
        "update_needs",
        "score_actions",
        "plan",
        "execute",
        "emit_events",
    ]


def test_repeated_plan_failure_marks_slow_loop_eligibility(single_tile_world: WorldState) -> None:
    """Repeated plan failures should mark the agent as slow-loop eligible."""

    slow_loop = RecordingSlowLoopService()
    runtime = _build_agent_runtime(slow_loop)

    for tick_number in range(1, 4):
        runtime.step_all(
            single_tile_world,
            _tick_at(hour=6, minute=tick_number),
            EventBus(),
        )

    assert single_tile_world.agents[0].plan_failure_count == 3
    assert slow_loop.last_seen_flags_by_agent == {"agent-1": {"repeated_plan_failure"}}


def test_day_rollover_marks_slow_loop_eligibility(simple_world: WorldState) -> None:
    """Day rollover should mark agents as eligible for the slow loop."""

    slow_loop = RecordingSlowLoopService()
    world_loop = WorldLoop(
        world_state=simple_world,
        sim_clock=SimulationClock(
            start_time=datetime(2000, 1, 1, 23, 59, tzinfo=timezone.utc),
            tick_interval=timedelta(minutes=2),
        ),
        scheduler=TaskScheduler(),
        agent_runtime=_build_agent_runtime(slow_loop),
        telemetry=TelemetryRecorder(),
        event_bus=EventBus(),
    )
    simple_world.current_time = datetime(2000, 1, 1, 23, 59, tzinfo=timezone.utc)
    simple_world.day_index = simple_world.current_time.toordinal()

    world_loop.tick_once()

    assert slow_loop.last_seen_flags_by_agent == {"agent-1": {"day_rollover"}}


def test_fast_loop_tests_do_not_require_reflection_dependencies(simple_world: WorldState) -> None:
    """A normal fast-loop step should not depend on any reflection or LLM work."""

    runtime = _build_agent_runtime(_real_slow_loop_service(ExplodingReflectionWorkflow()))

    runtime.step_all(simple_world, _tick_at(hour=6, minute=5), EventBus())

    assert runtime.last_step_traces[0].selected_action != ""


def _build_agent_runtime(slow_loop_service: object) -> AgentRuntime:
    """Build a real fast-loop runtime with a caller-provided slow-loop boundary."""

    return AgentRuntime(
        perception_service=PerceptionService(),
        need_service=NeedService(),
        utility_ai=UtilityAI(),
        planner=ActionPlanner(),
        executor=ActionExecutor(),
        slow_loop_service=slow_loop_service,  # type: ignore[arg-type]
    )


def _real_slow_loop_service(reflection_workflow: ReflectionWorkflow) -> SlowLoopService:
    """Build the real slow-loop service with a caller-provided reflection boundary."""

    return SlowLoopService(
        memory_retriever=MemoryRetriever(),
        autobiography_builder=AutobiographyBuilder(),
        reflection_workflow=reflection_workflow,
        validator=ReflectionValidator(),
        goal_updater=GoalUpdater(),
        belief_updater=BeliefUpdater(),
        memory_writer=MemoryWriter(),
    )


def _tick_at(hour: int, minute: int) -> SimTick:
    """Construct a deterministic tick for fast-loop unit tests."""

    return SimTick(
        tick=1,
        at=datetime(2000, 1, 1, hour, minute, tzinfo=timezone.utc),
        previous_day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
    )
