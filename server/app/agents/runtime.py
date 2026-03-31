"""Agent runtime coordinating fast and slow loops."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.executor import ActionExecutor
from app.agents.needs import NeedService
from app.agents.perception import PerceptionService
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
    selected_action: str = ""
    planner_hints_before: list[str] = field(default_factory=list)
    planner_hints_after: list[str] = field(default_factory=list)


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
    ) -> None:
        self._perception_service = perception_service
        self._need_service = need_service
        self._utility_ai = utility_ai
        self._planner = planner
        self._executor = executor
        self._slow_loop_service = slow_loop_service
        self.last_step_traces: list[AgentStepTrace] = []

    def step_all(self, world: WorldState, tick: SimTick, event_bus: EventBus) -> list[SimulationEvent]:
        """Advance all agents by one fast-loop step and process slow-loop triggers."""

        emitted_events: list[SimulationEvent] = []
        self.last_step_traces = []

        for agent in world.agents:
            trace = AgentStepTrace(agent_id=agent.agent_id)
            self.last_step_traces.append(trace)
            emitted_events.extend(self._step_agent(world, agent, tick, event_bus, trace))

        emitted_events.extend(self._slow_loop_service.handle_post_fast_loop(world, tick, event_bus))
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

        trace.stage_order.append("update_needs")
        self._need_service.update(agent)

        trace.stage_order.append("score_actions")
        candidates = self._utility_ai.score_actions(agent, context)

        trace.stage_order.append("plan")
        trace.planner_hints_before = list(agent.pending_planner_hints)
        selected_action = self._planner.choose_action(agent, candidates)
        trace.selected_action = selected_action.action_type.value
        self._consume_planner_hints(agent, selected_action.action_type.value)
        trace.planner_hints_after = list(agent.pending_planner_hints)

        trace.stage_order.append("execute")
        events = self._executor.execute(world, agent, selected_action, tick.tick, tick.at, event_bus)

        trace.stage_order.append("emit_events")
        for event in events:
            if event.type is EventType.PLAN_FAILED and agent.plan_failure_count >= 3:
                agent.slow_loop_trigger_flags.add("repeated_plan_failure")

        return events

    @staticmethod
    def _consume_planner_hints(agent: AgentState, selected_action: str) -> None:
        """Consume planner hints once they influence the chosen fast-loop action."""

        action_to_hint = {
            "eat": "eat_soon",
            "drink": "drink_soon",
            "rest": "rest_soon",
        }
        matched_hint = action_to_hint.get(selected_action)
        if matched_hint and matched_hint in agent.pending_planner_hints:
            agent.pending_planner_hints.remove(matched_hint)
