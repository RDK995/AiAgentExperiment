"""Slow-loop trigger evaluation and reflection application."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.reflection import ReflectionWorkflow
from app.cognition.reflection_graph import AutobiographyBuilder
from app.cognition.validation import ReflectionValidationError, ReflectionValidator
from app.engine.event_bus import EventBus
from app.engine.sim_clock import SimTick
from app.engine.world_state import AgentState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.writer import MemoryWriter
from app.schemas.event import EventType, SimulationEvent
from app.schemas.reflection import ReflectionContext


@dataclass(slots=True)
class SlowLoopResult:
    """Recorded slow-loop outcome for debugging and tests."""

    agent_id: str
    trigger_reasons: list[str] = field(default_factory=list)
    applied: bool = False
    planner_hints: list[str] = field(default_factory=list)


class SlowLoopService:
    """Evaluates triggers and runs the slow-loop reflection workflow."""

    def __init__(
        self,
        memory_retriever: MemoryRetriever,
        autobiography_builder: AutobiographyBuilder,
        reflection_workflow: ReflectionWorkflow,
        validator: ReflectionValidator,
        goal_updater: GoalUpdater,
        belief_updater: BeliefUpdater,
        memory_writer: MemoryWriter,
    ) -> None:
        self._memory_retriever = memory_retriever
        self._autobiography_builder = autobiography_builder
        self._reflection_workflow = reflection_workflow
        self._validator = validator
        self._goal_updater = goal_updater
        self._belief_updater = belief_updater
        self._memory_writer = memory_writer
        self.last_results: list[SlowLoopResult] = []

    def handle_post_fast_loop(
        self,
        world: WorldState,
        tick: SimTick,
        event_bus: EventBus,
    ) -> list[SimulationEvent]:
        """Consume events, set trigger flags, and run due slow loops."""

        events = event_bus.drain()
        self.last_results = []

        for event in events:
            self._apply_event_trigger(world, event)

        replayed_events: list[SimulationEvent] = list(events)
        for agent in world.agents:
            if not agent.slow_loop_trigger_flags:
                continue

            result = self._run_for_agent(agent, world, tick, event_bus)
            self.last_results.append(result)

        for event in replayed_events:
            event_bus.emit(event)
        return replayed_events

    def _apply_event_trigger(self, world: WorldState, event: SimulationEvent) -> None:
        if event.type is EventType.DAY_ROLLOVER:
            next_day_index = event.payload.get("day_index")
            for agent in world.agents:
                if next_day_index is not None and agent.daily_summary_day_index != next_day_index:
                    agent.daily_summary_day_index = next_day_index
                    agent.daily_summary_candidates = []
                agent.slow_loop_trigger_flags.add("day_rollover")
            return

        if event.agent_id is None:
            return

        agent = world.agent_by_id(event.agent_id)
        if agent is None:
            return

        if event.type is EventType.PLAN_FAILED and agent.plan_failure_count >= 3:
            agent.slow_loop_trigger_flags.add("repeated_plan_failure")
        elif event.type is EventType.MAJOR_LIFE_EVENT:
            agent.slow_loop_trigger_flags.add("major_life_event")
        elif event.type is EventType.SOCIAL_MILESTONE:
            agent.slow_loop_trigger_flags.add("social_milestone")

    def _run_for_agent(
        self,
        agent: AgentState,
        world: WorldState,
        tick: SimTick,
        event_bus: EventBus,
    ) -> SlowLoopResult:
        trigger_reasons = sorted(agent.slow_loop_trigger_flags)
        recent_events = self._memory_retriever.retrieve_recent_events(agent)
        autobiography = self._autobiography_builder.build(agent, recent_events)
        context = ReflectionContext(
            agent_id=agent.agent_id,
            trigger_reasons=trigger_reasons,
            autobiography=autobiography,
            recent_events=recent_events,
        )
        raw_result = self._reflection_workflow.run(agent, context)
        try:
            validated_result = self._validator.validate(raw_result)
        except ReflectionValidationError:
            return SlowLoopResult(
                agent_id=agent.agent_id,
                trigger_reasons=trigger_reasons,
                applied=False,
            )

        self._goal_updater.apply(agent, validated_result.goals)
        self._belief_updater.apply(agent, validated_result.beliefs)
        self._memory_writer.write(agent, validated_result.memory_entries)
        agent.pending_planner_hints = list(validated_result.planner_hints)
        agent.slow_loop_trigger_flags.clear()
        event_bus.emit(
            SimulationEvent(
                type=EventType.SLOW_LOOP_COMPLETED,
                tick=tick.tick,
                sim_time=tick.at,
                agent_id=agent.agent_id,
                actor_ids=[agent.agent_id],
                location_x=agent.x,
                location_y=agent.y,
                source_module="slow_loop",
                payload={"planner_hints": list(validated_result.planner_hints)},
            )
        )
        return SlowLoopResult(
            agent_id=agent.agent_id,
            trigger_reasons=trigger_reasons,
            applied=True,
            planner_hints=list(validated_result.planner_hints),
        )
