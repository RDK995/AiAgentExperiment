"""Phase 2 unit tests for slow-loop triggers, validation, and planner-hint gating."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import pytest

from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.slow_loop import SlowLoopService
from app.cognition.validation import ReflectionValidationError, ReflectionValidator
from app.engine.event_bus import EventBus
from app.engine.sim_clock import SimTick
from app.engine.world_state import AgentState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.schemas.event import EventType, SimulationEvent
from app.schemas.reflection import MemoryCandidate
from app.schemas.reflection import ReflectionContext, ReflectionResult


@dataclass(slots=True)
class SpyMemoryRetriever:
    """Memory retriever spy for verifying slow-loop context collection."""

    returned_events: list[str]
    calls: list[str] = field(default_factory=list)

    def retrieve_recent_events(self, agent: AgentState) -> list[str]:
        self.calls.append(agent.agent_id)
        return list(self.returned_events)


@dataclass(slots=True)
class SpyAutobiographyBuilder:
    """Autobiography builder spy for verifying compact slice construction."""

    output: str
    calls: list[tuple[str, list[str]]] = field(default_factory=list)

    def build(self, agent: AgentState, recent_events: list[str]) -> str:
        self.calls.append((agent.agent_id, list(recent_events)))
        return self.output


@dataclass(slots=True)
class SpyReflectionWorkflow:
    """Reflection workflow spy that returns a structured predetermined result."""

    result: ReflectionResult
    calls: list[ReflectionContext] = field(default_factory=list)

    def run(self, agent: AgentState, context: ReflectionContext) -> ReflectionResult:
        self.calls.append(context)
        return self.result


@dataclass(slots=True)
class RejectingValidator:
    """Validation stub that rejects all reflection outputs."""

    calls: list[ReflectionResult] = field(default_factory=list)

    def validate(self, result: ReflectionResult) -> ReflectionResult:
        self.calls.append(result)
        raise ReflectionValidationError("Rejected by test validator.")


@dataclass(slots=True)
class SpyGoalUpdater:
    """Goal updater spy for verifying post-validation writes."""

    calls: list[list[str]] = field(default_factory=list)

    def apply(self, agent: AgentState, goals: list[str]) -> None:
        self.calls.append(list(goals))
        if goals:
            agent.current_goal = goals[0]


@dataclass(slots=True)
class SpyBeliefUpdater:
    """Belief updater spy for verifying post-validation writes."""

    calls: list[list[str]] = field(default_factory=list)

    def apply(self, agent: AgentState, beliefs: list[str]) -> None:
        self.calls.append(list(beliefs))
        agent.beliefs = list(beliefs)


@dataclass(slots=True)
class SpyMemoryWriter:
    """Memory writer spy for verifying post-validation writes."""

    calls: list[list[str]] = field(default_factory=list)

    def write(self, agent: AgentState, memory_entries: list[str]) -> None:
        self.calls.append(list(memory_entries))
        agent.memories.extend(memory_entries)


@pytest.fixture
def slow_loop_tick() -> SimTick:
    """Deterministic tick for slow-loop tests."""

    return SimTick(
        tick=7,
        at=datetime(2000, 1, 2, 9, 30, tzinfo=timezone.utc),
        previous_day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        day_index=datetime(2000, 1, 2, tzinfo=timezone.utc).toordinal(),
    )


def test_major_life_event_triggers_slow_loop(simple_world: WorldState, slow_loop_tick: SimTick) -> None:
    """Major life events should trigger a slow-loop run for the affected agent."""

    slow_loop, _, _, _, _, _, _ = _build_service()
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "bereavement"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)

    assert slow_loop.last_results[0].trigger_reasons == ["major_life_event"]
    assert slow_loop.last_results[0].applied is True


def test_social_milestone_triggers_slow_loop(simple_world: WorldState, slow_loop_tick: SimTick) -> None:
    """Social milestone events should trigger a slow-loop run for the affected agent."""

    slow_loop, _, _, _, _, _, _ = _build_service()
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.SOCIAL_MILESTONE,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "friendship"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)

    assert slow_loop.last_results[0].trigger_reasons == ["social_milestone"]
    assert slow_loop.last_results[0].applied is True


def test_slow_loop_retrieves_context_and_builds_autobiography(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """The slow loop should gather recent context before running reflection."""

    retriever = SpyMemoryRetriever(returned_events=["Met Alice", "Harvested berries"])
    builder = SpyAutobiographyBuilder(output="Autobiography slice")
    slow_loop, _, _, workflow, _, _, _ = _build_service(
        memory_retriever=retriever,
        autobiography_builder=builder,
    )
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "storm"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)

    assert retriever.calls == [simple_world.agents[0].agent_id]
    assert builder.calls == [
        (simple_world.agents[0].agent_id, ["Met Alice", "Harvested berries"])
    ]
    assert workflow.calls[0].recent_events == ["Met Alice", "Harvested berries"]
    assert workflow.calls[0].autobiography == "Autobiography slice"


def test_day_rollover_prioritizes_daily_summary_candidates_over_recent_memory_noise(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """Day-rollover reflection should see queued high-salience candidates before raw recency noise."""

    agent = simple_world.agents[0]
    agent.daily_summary_day_index = slow_loop_tick.day_index
    agent.daily_summary_candidates = [
        MemoryCandidate(text="Child born in my household.", salience=0.95, valence=0.8),
        MemoryCandidate(text="agent-2 gave me berries.", salience=0.90, valence=0.7),
    ]
    agent.memories = [
        "Shared a greeting.",
        "agent-2 gave me berries.",
        "Walked the village path.",
        "Cooked soup at dusk.",
    ]

    builder = SpyAutobiographyBuilder(output="Daily autobiography slice")
    slow_loop, _, _, workflow, _, _, _ = _build_service(
        memory_retriever=MemoryRetriever(),
        autobiography_builder=builder,
    )
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.DAY_ROLLOVER,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            payload={"day_index": slow_loop_tick.day_index},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)

    assert workflow.calls[0].recent_events == [
        "Child born in my household.",
        "agent-2 gave me berries.",
        "Cooked soup at dusk.",
        "Walked the village path.",
        "Shared a greeting.",
    ]
    assert builder.calls == [
        (
            agent.agent_id,
            [
                "Child born in my household.",
                "agent-2 gave me berries.",
                "Cooked soup at dusk.",
                "Walked the village path.",
                "Shared a greeting.",
            ],
        )
    ]
    assert slow_loop.last_results[0].trigger_reasons == ["day_rollover"]


def test_day_rollover_expires_stale_daily_summary_candidates_from_quiet_days(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """A quiet-day rollover should clear stale queued candidates before reflection context is built."""

    agent = simple_world.agents[0]
    agent.daily_summary_day_index = slow_loop_tick.day_index - 2
    agent.daily_summary_candidates = [
        MemoryCandidate(text="A child was born.", salience=0.95, valence=0.9),
    ]
    agent.memories = ["Cooked dinner.", "Walked the path."]

    builder = SpyAutobiographyBuilder(output="Quiet-day autobiography slice")
    slow_loop, _, _, workflow, _, _, _ = _build_service(
        memory_retriever=MemoryRetriever(),
        autobiography_builder=builder,
    )
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.DAY_ROLLOVER,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            payload={"day_index": slow_loop_tick.day_index},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)

    assert agent.daily_summary_day_index == slow_loop_tick.day_index
    assert agent.daily_summary_candidates == []
    assert workflow.calls[0].recent_events == ["Walked the path.", "Cooked dinner."]
    assert builder.calls == [
        (agent.agent_id, ["Walked the path.", "Cooked dinner."])
    ]


def test_reflection_output_is_validated_before_application(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """Validation must run before any state mutation is applied."""

    validator = RejectingValidator()
    goal_updater = SpyGoalUpdater()
    belief_updater = SpyBeliefUpdater()
    memory_writer = SpyMemoryWriter()
    slow_loop, _, _, workflow, _, _, _ = _build_service(
        validator=validator,
        goal_updater=goal_updater,
        belief_updater=belief_updater,
        memory_writer=memory_writer,
    )
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "loss"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)

    assert validator.calls == [workflow.result]
    assert goal_updater.calls == []
    assert belief_updater.calls == []
    assert memory_writer.calls == []
    assert simple_world.agents[0].current_goal == "Maintain daily routine"
    assert simple_world.agents[0].beliefs == []
    assert simple_world.agents[0].memories == []


def test_invalid_reflection_output_is_rejected(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """Rejected reflection outputs must not mutate state or planner hints."""

    validator = RejectingValidator()
    slow_loop, _, _, _, _, _, _ = _build_service(validator=validator)
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.SOCIAL_MILESTONE,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "bonding"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)
    replayed_events = event_bus.drain()

    assert slow_loop.last_results[0].applied is False
    assert simple_world.agents[0].pending_planner_hints == []
    assert all(event.type is not EventType.SLOW_LOOP_COMPLETED for event in replayed_events)


def test_empty_reflection_output_is_rejected(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """Empty structured reflection outputs must not consume the slow-loop trigger."""

    empty_result = ReflectionResult(
        goals=[],
        beliefs=[],
        memory_entries=[],
        planner_hints=[],
    )
    slow_loop, _, _, _, _, _, _ = _build_service(reflection_result=empty_result)
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "empty_reflection"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)
    replayed_events = event_bus.drain()

    assert slow_loop.last_results[0].applied is False
    assert slow_loop.last_results[0].planner_hints == []
    assert simple_world.agents[0].current_goal == "Maintain daily routine"
    assert simple_world.agents[0].beliefs == []
    assert simple_world.agents[0].memories == []
    assert simple_world.agents[0].pending_planner_hints == []
    assert "major_life_event" in simple_world.agents[0].slow_loop_trigger_flags
    assert all(event.type is not EventType.SLOW_LOOP_COMPLETED for event in replayed_events)


def test_valid_reflection_output_writes_goals_beliefs_and_memories(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """Validated reflection outputs should update authoritative slow-loop state."""

    reflection_result = ReflectionResult(
        goals=["Protect the village"],
        beliefs=["Working together improves resilience"],
        memory_entries=["Reflected on the village festival"],
        planner_hints=["rest_soon"],
    )
    goal_updater = SpyGoalUpdater()
    belief_updater = SpyBeliefUpdater()
    memory_writer = SpyMemoryWriter()
    slow_loop, _, _, _, _, _, _ = _build_service(
        reflection_result=reflection_result,
        goal_updater=goal_updater,
        belief_updater=belief_updater,
        memory_writer=memory_writer,
    )
    event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "festival"},
        )
    )

    slow_loop.handle_post_fast_loop(simple_world, slow_loop_tick, event_bus)

    assert goal_updater.calls == [["Protect the village"]]
    assert belief_updater.calls == [["Working together improves resilience"]]
    assert memory_writer.calls == [["Reflected on the village festival"]]
    assert simple_world.agents[0].current_goal == "Protect the village"
    assert simple_world.agents[0].beliefs == ["Working together improves resilience"]
    assert simple_world.agents[0].memories == ["Reflected on the village festival"]


def test_planner_hints_are_emitted_only_after_successful_validation(
    simple_world: WorldState,
    slow_loop_tick: SimTick,
) -> None:
    """Planner hints must be gated by successful reflection validation."""

    invalid_validator = RejectingValidator()
    invalid_service, _, _, _, _, _, _ = _build_service(validator=invalid_validator)
    invalid_event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "failed_case"},
        )
    )

    invalid_service.handle_post_fast_loop(simple_world, slow_loop_tick, invalid_event_bus)
    invalid_events = invalid_event_bus.drain()

    assert simple_world.agents[0].pending_planner_hints == []
    assert all(event.type is not EventType.SLOW_LOOP_COMPLETED for event in invalid_events)

    reflection_result = ReflectionResult(
        goals=["Recover and adapt"],
        beliefs=["Planning helps"],
        memory_entries=["Validated reflection entry"],
        planner_hints=["reflect_on_failures", "rest_soon"],
    )
    valid_service, _, _, _, _, _, _ = _build_service(reflection_result=reflection_result)
    valid_event_bus = _event_bus_for(
        SimulationEvent(
            type=EventType.MAJOR_LIFE_EVENT,
            tick=slow_loop_tick.tick,
            sim_time=slow_loop_tick.at,
            agent_id=simple_world.agents[0].agent_id,
            payload={"kind": "success_case"},
        )
    )

    valid_service.handle_post_fast_loop(simple_world, slow_loop_tick, valid_event_bus)
    valid_events = valid_event_bus.drain()

    assert simple_world.agents[0].pending_planner_hints == ["reflect_on_failures", "rest_soon"]
    completed_events = [event for event in valid_events if event.type is EventType.SLOW_LOOP_COMPLETED]
    assert len(completed_events) == 1
    assert completed_events[0].payload == {"planner_hints": ["reflect_on_failures", "rest_soon"]}


def _build_service(
    *,
    memory_retriever: SpyMemoryRetriever | None = None,
    autobiography_builder: SpyAutobiographyBuilder | None = None,
    reflection_result: ReflectionResult | None = None,
    validator: ReflectionValidator | RejectingValidator | None = None,
    goal_updater: GoalUpdater | SpyGoalUpdater | None = None,
    belief_updater: BeliefUpdater | SpyBeliefUpdater | None = None,
    memory_writer: MemoryWriter | SpyMemoryWriter | None = None,
) -> tuple[
    SlowLoopService,
    SpyMemoryRetriever,
    SpyAutobiographyBuilder,
    SpyReflectionWorkflow,
    ReflectionValidator | RejectingValidator,
    GoalUpdater | SpyGoalUpdater,
    BeliefUpdater | SpyBeliefUpdater,
]:
    """Build a slow-loop service with spy collaborators for Phase 2 tests."""

    retriever = memory_retriever or SpyMemoryRetriever(returned_events=["Remembered market day"])
    builder = autobiography_builder or SpyAutobiographyBuilder(output="Default autobiography slice")
    workflow = SpyReflectionWorkflow(
        result=reflection_result
        or ReflectionResult(
            goals=["Support village stability"],
            beliefs=["Careful routines improve outcomes"],
            memory_entries=["Reflected on a recent event"],
            planner_hints=["keep_routine"],
        )
    )
    validation = validator or ReflectionValidator()
    goal_writer = goal_updater or GoalUpdater()
    belief_writer = belief_updater or BeliefUpdater()
    memory_persister = memory_writer or MemoryWriter()

    return (
        SlowLoopService(
            memory_retriever=retriever,
            autobiography_builder=builder,
            reflection_workflow=workflow,
            validator=validation,
            goal_updater=goal_writer,
            belief_updater=belief_writer,
            memory_writer=memory_persister,
        ),
        retriever,
        builder,
        workflow,
        validation,
        goal_writer,
        belief_writer,
    )


def _event_bus_for(event: SimulationEvent) -> EventBus:
    """Create an event bus containing a single deterministic trigger event."""

    event_bus = EventBus()
    event_bus.emit(event)
    return event_bus
