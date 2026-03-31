"""Authoritative action execution for a single fast-loop step."""

from __future__ import annotations

from datetime import datetime

from app.agents.actions import ActionType, SelectedAction
from app.engine.event_bus import EventBus
from app.engine.rules.simulation_rules import is_action_legal
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent


class ActionExecutor:
    """Apply one deterministic action step to authoritative state."""

    def execute(
        self,
        world: WorldState,
        agent: AgentState,
        action: SelectedAction,
        tick: int,
        now: datetime,
        event_bus: EventBus,
    ) -> list[SimulationEvent]:
        """Execute one action step and emit resulting events."""

        agent.current_action = action.action_type.value
        events: list[SimulationEvent] = []

        if action.action_type is ActionType.EAT:
            agent.hunger = max(0.0, agent.hunger - 8.0)
        elif action.action_type is ActionType.DRINK:
            agent.thirst = max(0.0, agent.thirst - 10.0)
        elif action.action_type is ActionType.REST:
            agent.fatigue = max(0.0, agent.fatigue - 6.0)
        elif action.action_type is ActionType.WANDER:
            direction = 1 if tick % 2 == 0 else -1
            target_x = agent.x + direction
            if is_action_legal(world, agent, "move", target_x=target_x, target_y=agent.y):
                agent.x = target_x
                agent.plan_failure_count = 0
            else:
                agent.plan_failure_count += 1
                failure_event = SimulationEvent(
                    type=EventType.PLAN_FAILED,
                    tick=tick,
                    sim_time=now,
                    agent_id=agent.agent_id,
                    payload={"attempted_action": action.action_type.value},
                )
                event_bus.emit(failure_event)
                events.append(failure_event)
        else:
            agent.plan_failure_count = max(0, agent.plan_failure_count - 1)

        executed_event = SimulationEvent(
            type=EventType.ACTION_EXECUTED,
            tick=tick,
            sim_time=now,
            agent_id=agent.agent_id,
            payload={
                "action": action.action_type.value,
                "position": {"x": agent.x, "y": agent.y},
            },
        )
        event_bus.emit(executed_event)
        events.append(executed_event)
        return events
