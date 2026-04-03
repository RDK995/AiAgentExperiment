"""Agent runtime coordinating fast and slow loops."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.agents.executor import ActionExecutor
from app.agents.lifecycle import LifecycleService
from app.agents.needs import NeedService
from app.agents.perception import PerceptionResult, PerceptionService
from app.agents.planner import ActionPlanner
from app.agents.utility_ai import UtilityAI
from app.cognition.slow_loop import SlowLoopService
from app.engine.event_bus import EventBus
from app.engine.sim_clock import SimTick
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent


@dataclass(slots=True)
class AgentStepTrace:
    """Execution trace for a single agent fast-loop step."""

    agent_id: str
    stage_order: list[str] = field(default_factory=list)
    perception_summary: dict[str, Any] = field(default_factory=dict)
    top_action_candidates: list[dict[str, float | str]] = field(default_factory=list)
    selected_action: str = ""
    planned_tasks: list[str] = field(default_factory=list)
    planner_hints_before: list[str] = field(default_factory=list)
    planner_hints_after: list[str] = field(default_factory=list)
    emitted_event_types: list[str] = field(default_factory=list)


class AgentRuntime:
    """Runs fast and slow loops for all authoritative agents."""

    def __init__(
        self,
        perception_service: PerceptionService,
        need_service: NeedService,
        utility_ai: UtilityAI,
        planner: ActionPlanner,
        executor: ActionExecutor,
        slow_loop_service: SlowLoopService,
        lifecycle_service: LifecycleService | None = None,
    ) -> None:
        self._perception_service = perception_service
        self._need_service = need_service
        self._utility_ai = utility_ai
        self._planner = planner
        self._executor = executor
        self._slow_loop_service = slow_loop_service
        self._lifecycle_service = lifecycle_service
        self.last_step_traces: list[AgentStepTrace] = []
        self.last_fast_loop_event_types: list[str] = []
        self.last_lifecycle_event_types: list[str] = []
        self.last_slow_loop_event_types: list[str] = []

    def step_all(self, world: WorldState, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
        """Advance all agents by one fast-loop step and process slow-loop triggers."""

        emitted_events: list[SimulationEvent] = []
        self.last_step_traces = []
        self.last_fast_loop_event_types = []
        self.last_lifecycle_event_types = []
        self.last_slow_loop_event_types = []

        for agent in world.agents:
            if not agent.alive:
                continue
            trace = AgentStepTrace(agent_id=agent.agent_id)
            self.last_step_traces.append(trace)
            agent_events = self._step_agent(world, agent, tick, event_bus, trace)
            emitted_events.extend(agent_events)
            self.last_fast_loop_event_types.extend(event.type.value for event in agent_events)

        if self._lifecycle_service is not None:
            lifecycle_events = self._lifecycle_service.update(world, tick.tick, tick.at, event_bus)
            emitted_events.extend(lifecycle_events)
            self.last_lifecycle_event_types = [event.type.value for event in lifecycle_events]

        slow_loop_events = self._slow_loop_service.handle_post_fast_loop(world, tick, event_bus)
        emitted_events.extend(slow_loop_events)
        self.last_slow_loop_event_types = [event.type.value for event in slow_loop_events]
        return emitted_events

    def _step_agent(
        self,
        world: WorldState,
        agent: AgentState,
        tick: SimTick,
        event_bus: EventBus,
        trace: AgentStepTrace,
    ) -> list[SimulationEvent]:
        trace.stage_order.append("perceive")
        context = self._perception_service.perceive(world, agent, tick.at)
        trace.perception_summary = self._summarize_perception(context)

        trace.stage_order.append("update_needs")
        self._need_service.update(agent)
        context = self._perception_service.perceive(world, agent, tick.at)
        trace.perception_summary = self._summarize_perception(context)

        trace.stage_order.append("score_actions")
        candidates = self._utility_ai.score_actions(agent, context)
        trace.top_action_candidates = [
            {"action": candidate.action_type.value, "score": candidate.score}
            for candidate in candidates[:3]
        ]

        trace.stage_order.append("plan")
        trace.planner_hints_before = list(agent.pending_planner_hints)
        selected_action = self._planner.choose_action(agent, candidates, context)
        trace.selected_action = selected_action.action_type.value
        trace.planned_tasks = [task.task_type.value for task in selected_action.tasks]
        self._consume_planner_hints(agent, selected_action.action_type.value)
        trace.planner_hints_after = list(agent.pending_planner_hints)

        trace.stage_order.append("execute")
        events = self._executor.execute(world, agent, selected_action, tick.tick, tick.at, event_bus, context)

        trace.stage_order.append("emit_events")
        trace.emitted_event_types = [event.type.value for event in events]
        for event in events:
            if event.type is EventType.PLAN_FAILED and agent.plan_failure_count >= 3:
                agent.slow_loop_trigger_flags.add("repeated_plan_failure")

        return events

    @staticmethod
    def _consume_planner_hints(agent: AgentState, selected_action: str) -> None:
        """Consume planner hints once they influence the chosen fast-loop action."""

        action_to_hints = {
            "eat": ["eat_soon", "focus_on_recovery", "prioritize_food_security"],
            "drink": ["drink_soon", "focus_on_recovery"],
            "rest": ["rest_soon", "focus_on_recovery"],
            "gather_food": ["prioritize_food_security", "gather_resources"],
            "fetch_water": ["gather_resources", "focus_on_recovery"],
            "work_field": ["gather_resources", "prioritize_food_security"],
            "socialize": ["visit_partner"],
            "court": ["visit_partner"],
            "wander": ["reflect_on_failures"],
        }
        for matched_hint in action_to_hints.get(selected_action, []):
            if matched_hint in agent.pending_planner_hints:
                agent.pending_planner_hints.remove(matched_hint)
                break

    @staticmethod
    def _summarize_perception(context: PerceptionResult) -> dict[str, Any]:
        """Reduce the perception model to a compact debug trace."""

        return {
            "visible_agent_ids": list(context.visible_agents),
            "visible_item_ids": list(context.visible_items),
            "visible_resource_ids": list(context.visible_resources),
            "nearby_water": context.nearby_water,
            "nearby_food": context.nearby_food,
            "nearby_threat": context.nearby_threat,
            "nearby_infant_ids": list(context.nearby_infant_ids),
            "nearest_water": (
                {"x": context.nearest_water_x, "y": context.nearest_water_y}
                if context.nearest_water_x is not None and context.nearest_water_y is not None
                else None
            ),
            "nearest_food": (
                {"x": context.nearest_food_x, "y": context.nearest_food_y}
                if context.nearest_food_x is not None and context.nearest_food_y is not None
                else None
            ),
            "nearest_infant": (
                {"x": context.nearest_infant_x, "y": context.nearest_infant_y}
                if context.nearest_infant_x is not None and context.nearest_infant_y is not None
                else None
            ),
            "terrain": context.terrain,
            "weather": context.weather,
            "sim_hour": context.sim_hour,
        }
