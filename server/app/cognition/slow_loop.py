"""Slow-loop trigger evaluation and reflection application."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.reflection import ReflectionWorkflow
from app.cognition.reflection_graph import AutobiographyBuilder
from app.cognition.triggers import ReflectionTriggerEvaluator
from app.cognition.validation import ReflectionValidationError, ReflectionValidator
from app.engine.event_bus import EventBus
from app.engine.sim_clock import SimTick
from app.engine.world_state import AgentState, WorldState
from app.memory.retriever import MemoryRetriever
from app.memory.retrieval import RetrievalContextService
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
    failure_stage: str | None = None
    validation_errors: list[str] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)
    retrieved_memory_count: int = 0
    token_cost: float = 0.0


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
        retrieval_service: RetrievalContextService | None = None,
        trigger_evaluator: ReflectionTriggerEvaluator | None = None,
    ) -> None:
        self._memory_retriever = memory_retriever
        self._autobiography_builder = autobiography_builder
        self._reflection_workflow = reflection_workflow
        self._validator = validator
        self._goal_updater = goal_updater
        self._belief_updater = belief_updater
        self._memory_writer = memory_writer
        self._retrieval_service = retrieval_service
        self._trigger_evaluator = trigger_evaluator or ReflectionTriggerEvaluator()
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
        self._trigger_evaluator.apply_state_triggers(world)

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
        self._trigger_evaluator.apply_event_trigger(world, event)

    def _run_for_agent(
        self,
        agent: AgentState,
        world: WorldState,
        tick: SimTick,
        event_bus: EventBus,
    ) -> SlowLoopResult:
        trigger_reasons = sorted(agent.slow_loop_trigger_flags)
        if self._retrieval_service is not None:
            retrieved_context = self._retrieval_service.retrieve_context(
                agent,
                query_text=self._build_query_text(agent, trigger_reasons),
            )
            retrieved_memory_count = len(retrieved_context.memories)
            recent_events = [memory.raw_text for memory in retrieved_context.memories]
            autobiography = retrieved_context.summary
            goals = [goal.title for goal in retrieved_context.goals]
            relationships = [relationship.related_agent_id for relationship in retrieved_context.relationships]
        else:
            recent_events = self._memory_retriever.retrieve_recent_events(agent)
            retrieved_memory_count = len(recent_events)
            autobiography = self._autobiography_builder.build(agent, recent_events)
            goals = []
            relationships = []
        context = ReflectionContext(
            agent_id=agent.agent_id,
            trigger_reasons=trigger_reasons,
            autobiography=autobiography,
            recent_events=recent_events,
            goals=goals,
            relationships=relationships,
        )
        if hasattr(self._reflection_workflow, "execute"):
            execution = self._reflection_workflow.execute(
                agent,
                world,
                context,
                validator=self._validator,
                goal_updater=self._goal_updater,
                belief_updater=self._belief_updater,
                memory_writer=self._memory_writer,
            )
            if not execution.success or execution.result is None:
                return SlowLoopResult(
                    agent_id=agent.agent_id,
                    trigger_reasons=trigger_reasons,
                    applied=False,
                    failure_stage=execution.failure_stage,
                    validation_errors=list(execution.validation_errors),
                    completed_stages=list(execution.completed_stages),
                    retrieved_memory_count=retrieved_memory_count,
                    token_cost=0.0,
                )
            validated_result = execution.result
            completed_stages = list(execution.completed_stages)
        else:
            raw_result = self._reflection_workflow.run(agent, context)
            try:
                validated_result = self._validator.validate(raw_result)
            except ReflectionValidationError as exc:
                return SlowLoopResult(
                    agent_id=agent.agent_id,
                    trigger_reasons=trigger_reasons,
                    applied=False,
                    failure_stage="validate",
                    validation_errors=[str(exc)],
                    completed_stages=[
                        "load_state",
                        "retrieve_context",
                        "build_prompt",
                        "call_model",
                        "parse_json",
                    ],
                    retrieved_memory_count=retrieved_memory_count,
                    token_cost=0.0,
                )

            self._goal_updater.apply(agent, validated_result.goals)
            self._belief_updater.apply(agent, validated_result.beliefs)
            self._memory_writer.write(agent, validated_result.memory_entries)
            agent.pending_planner_hints = list(validated_result.planner_hints)
            completed_stages = [
                "load_state",
                "retrieve_context",
                "build_prompt",
                "call_model",
                "parse_json",
                "validate",
                "persist_updates",
                "emit_planner_hints",
            ]
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
            completed_stages=completed_stages,
            retrieved_memory_count=retrieved_memory_count,
            token_cost=0.0,
        )

    @staticmethod
    def _build_query_text(agent: AgentState, trigger_reasons: list[str]) -> str:
        """Build a compact deterministic retrieval query for reflection context."""

        trigger_text = " ".join(trigger_reasons)
        return " ".join(part for part in [agent.current_goal, agent.current_action, trigger_text] if part).strip()
