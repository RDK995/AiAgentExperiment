"""Authoritative action execution for a single fast-loop step."""

from __future__ import annotations

from datetime import datetime

from app.agents.actions import ActionType, PlannedTask, SelectedAction, TaskType
from app.agents.perception import PerceptionResult
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
        perception: PerceptionResult | None = None,
    ) -> list[SimulationEvent]:
        """Execute one action step and emit resulting events."""

        agent.current_action = action.action_type.value
        events: list[SimulationEvent] = []
        previous_task_payload = agent.current_task_payload

        if action.interrupted_previous_action and agent.current_task_payload is not None:
            events.append(
                self._emit_event(
                    event_bus,
                    EventType.TASK_INTERRUPTED,
                    tick,
                    now,
                    agent,
                    {"task": agent.current_task_payload["task_type"]},
                )
            )

        self._ensure_plan_state(agent, action)
        task = self._current_task(agent)

        if task is None:
            agent.plan_failure_count += 1
            failure_event = self._emit_event(
                event_bus,
                EventType.PLAN_FAILED,
                tick,
                now,
                agent,
                {"attempted_action": action.action_type.value},
            )
            events.append(failure_event)
            events.append(self._emit_action_executed(event_bus, tick, now, agent, action.action_type))
            return events

        if agent.current_task_payload == task.to_payload() and previous_task_payload == task.to_payload():
            pass
        elif previous_task_payload is None or previous_task_payload["task_type"] != task.task_type.value:
            events.append(
                self._emit_event(
                    event_bus,
                    EventType.TASK_STARTED,
                    tick,
                    now,
                    agent,
                    {"task": task.task_type.value},
                )
            )
        agent.current_task_payload = task.to_payload()

        if action.action_type is ActionType.FLEE or (perception is not None and perception.nearby_threat):
            task = PlannedTask(TaskType.FLEE_STEP)

        completed = self._step_task(world, agent, task, tick, now, event_bus, events)
        if completed:
            if agent.task_queue:
                agent.task_queue.pop(0)
            agent.current_task_payload = agent.task_queue[0] if agent.task_queue else None

        events.append(self._emit_action_executed(event_bus, tick, now, agent, action.action_type))
        return events

    def _ensure_plan_state(self, agent: AgentState, action: SelectedAction) -> None:
        """Replace the agent's task queue when a new or interrupted plan is selected."""

        if action.interrupted_previous_action or not agent.task_queue or agent.current_action != action.action_type.value:
            agent.task_queue = [task.to_payload() for task in action.tasks]
            agent.current_task_payload = agent.task_queue[0] if agent.task_queue else None

    @staticmethod
    def _current_task(agent: AgentState) -> PlannedTask | None:
        """Return the current executable task from agent state."""

        if not agent.task_queue:
            return None
        return PlannedTask.from_payload(agent.task_queue[0])

    def _step_task(
        self,
        world: WorldState,
        agent: AgentState,
        task: PlannedTask,
        tick: int,
        now: datetime,
        event_bus: EventBus,
        events: list[SimulationEvent],
    ) -> bool:
        """Step a single planned task and return whether it completed."""

        if task.task_type is TaskType.WANDER_STEP:
            destination = self._select_wander_destination(world, agent, tick)
            if destination is None:
                agent.plan_failure_count += 1
                events.append(
                    self._emit_event(
                        event_bus,
                        EventType.PLAN_FAILED,
                        tick,
                        now,
                        agent,
                        {"attempted_task": task.task_type.value},
                    )
                )
                return False
            agent.x, agent.y = destination
            agent.plan_failure_count = 0
            events.append(
                self._emit_event(
                    event_bus,
                    EventType.TASK_COMPLETED,
                    tick,
                    now,
                    agent,
                    {"task": task.task_type.value, "position": {"x": agent.x, "y": agent.y}},
                )
            )
            return True

        if task.task_type is TaskType.FLEE_STEP:
            destination = self._select_flee_destination(world, agent)
            if destination is None:
                agent.plan_failure_count += 1
                events.append(
                    self._emit_event(
                        event_bus,
                        EventType.PLAN_FAILED,
                        tick,
                        now,
                        agent,
                        {"attempted_task": task.task_type.value},
                    )
                )
                return False
            agent.x, agent.y = destination
            agent.safety = min(100.0, agent.safety + 5.0)
            events.append(
                self._emit_event(
                    event_bus,
                    EventType.TASK_COMPLETED,
                    tick,
                    now,
                    agent,
                    {"task": task.task_type.value, "position": {"x": agent.x, "y": agent.y}},
                )
            )
            agent.plan_failure_count = 0
            return True

        if task.task_type is TaskType.DRINK:
            agent.thirst = max(0.0, agent.thirst - 10.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.EAT:
            agent.hunger = max(0.0, agent.hunger - 8.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.REST:
            agent.fatigue = max(0.0, agent.fatigue - 6.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.GATHER_FOOD:
            if not self._consume_food_source(world, agent):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.hunger = max(0.0, agent.hunger - 4.0)
            agent.memories.append("Gathered food nearby.")
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.FETCH_WATER:
            if not self._consume_water_source(world, agent):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.thirst = max(0.0, agent.thirst - 4.0)
            agent.memories.append("Fetched fresh water.")
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.COOK:
            agent.hunger = max(0.0, agent.hunger - 5.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.SOCIALIZE:
            agent.loneliness = max(0.0, agent.loneliness - 8.0)
            agent.morale = min(100.0, agent.morale + 2.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.COURT:
            agent.hope = min(100.0, agent.hope + 2.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.CARE_FOR_CHILD:
            agent.stress = max(0.0, agent.stress - 3.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.WORK_FIELD:
            agent.current_goal = "Maintain village resources"
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type in {TaskType.INSPECT_STOCK, TaskType.DISTRIBUTE_FOOD}:
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)

        return self._move_toward_target(world, agent, task, tick, now, event_bus, events)

    def _move_toward_target(
        self,
        world: WorldState,
        agent: AgentState,
        task: PlannedTask,
        tick: int,
        now: datetime,
        event_bus: EventBus,
        events: list[SimulationEvent],
    ) -> bool:
        """Take a single deterministic step toward the task target."""

        target_x = task.target_x if task.target_x is not None else agent.x
        target_y = task.target_y if task.target_y is not None else agent.y
        if agent.x == target_x and agent.y == target_y:
            agent.plan_failure_count = 0
            events.append(
                self._emit_event(
                    event_bus,
                    EventType.TASK_COMPLETED,
                    tick,
                    now,
                    agent,
                    {"task": task.task_type.value, "position": {"x": agent.x, "y": agent.y}},
                )
            )
            return True

        next_step = self._step_toward_target(world, agent, target_x, target_y)
        if next_step is None:
            return self._fail_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                extra_payload={"target": {"x": target_x, "y": target_y}},
            )

        agent.x, agent.y = next_step
        events.append(
            self._emit_event(
                event_bus,
                EventType.TASK_PROGRESS,
                tick,
                now,
                agent,
                {"task": task.task_type.value, "position": {"x": agent.x, "y": agent.y}},
            )
        )
        if agent.x == target_x and agent.y == target_y:
            agent.plan_failure_count = 0
            events.append(
                self._emit_event(
                    event_bus,
                    EventType.TASK_COMPLETED,
                    tick,
                    now,
                    agent,
                    {"task": task.task_type.value, "position": {"x": agent.x, "y": agent.y}},
                )
            )
            return True
        return False

    def _complete_non_move_task(
        self,
        event_bus: EventBus,
        tick: int,
        now: datetime,
        agent: AgentState,
        task: PlannedTask,
        events: list[SimulationEvent],
    ) -> bool:
        """Emit a completion event for a non-movement task."""

        agent.plan_failure_count = 0
        events.append(
            self._emit_event(
                event_bus,
                EventType.TASK_COMPLETED,
                tick,
                now,
                agent,
                {"task": task.task_type.value},
            )
        )
        return True

    def _fail_task(
        self,
        event_bus: EventBus,
        tick: int,
        now: datetime,
        agent: AgentState,
        task: PlannedTask,
        events: list[SimulationEvent],
        extra_payload: dict[str, object] | None = None,
    ) -> bool:
        """Record a plan failure for an unexecutable task."""

        agent.plan_failure_count += 1
        payload: dict[str, object] = {"attempted_task": task.task_type.value}
        if extra_payload is not None:
            payload.update(extra_payload)
        events.append(self._emit_event(event_bus, EventType.PLAN_FAILED, tick, now, agent, payload))
        return False

    def _consume_food_source(self, world: WorldState, agent: AgentState) -> bool:
        """Consume one unit of food from the authoritative world at the agent location."""

        for index, item in enumerate(world.items):
            if (item.x, item.y) == (agent.x, agent.y) and item.item_type in {"food", "berries", "fruit", "meal"}:
                item.quantity -= 1
                if item.quantity <= 0:
                    world.items.pop(index)
                return True

        for resource in world.resources:
            if (resource.x, resource.y) == (agent.x, agent.y) and resource.resource_type in {"berries", "field", "orchard", "fish"}:
                if resource.quantity <= 0:
                    return False
                resource.quantity = max(0, resource.quantity - 1)
                return True

        return False

    def _consume_water_source(self, world: WorldState, agent: AgentState) -> bool:
        """Consume or access a water source from the authoritative world near the agent."""

        for index, resource in enumerate(world.resources):
            if (resource.x, resource.y) == (agent.x, agent.y) and resource.resource_type == "water":
                resource.quantity -= 1
                if resource.quantity <= 0:
                    world.resources.pop(index)
                return True

        if world.terrain_at(agent.x, agent.y) == "water":
            return True

        for delta_x, delta_y in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            if world.terrain_at(agent.x + delta_x, agent.y + delta_y) == "water":
                return True
        return False

    def _emit_action_executed(
        self,
        event_bus: EventBus,
        tick: int,
        now: datetime,
        agent: AgentState,
        action_type: ActionType,
    ) -> SimulationEvent:
        """Emit the compatibility action-executed event."""

        return self._emit_event(
            event_bus,
            EventType.ACTION_EXECUTED,
            tick,
            now,
            agent,
            {"action": action_type.value, "position": {"x": agent.x, "y": agent.y}},
        )

    @staticmethod
    def _emit_event(
        event_bus: EventBus,
        event_type: EventType,
        tick: int,
        now: datetime,
        agent: AgentState,
        payload: dict[str, object],
    ) -> SimulationEvent:
        """Create, enqueue, and return a simulation event."""

        event = SimulationEvent(
            type=event_type,
            tick=tick,
            sim_time=now,
            agent_id=agent.agent_id,
            payload=payload,
        )
        event_bus.emit(event)
        return event

    @staticmethod
    def _step_toward_target(
        world: WorldState,
        agent: AgentState,
        target_x: int,
        target_y: int,
    ) -> tuple[int, int] | None:
        """Take one deterministic step that reduces distance to the target."""

        options: list[tuple[int, int]] = []
        if target_x != agent.x:
            step_x = agent.x + (1 if target_x > agent.x else -1)
            options.append((step_x, agent.y))
        if target_y != agent.y:
            step_y = agent.y + (1 if target_y > agent.y else -1)
            options.append((agent.x, step_y))

        for x, y in options:
            if is_action_legal(world, agent, "move", target_x=x, target_y=y):
                return x, y
        return None

    @staticmethod
    def _select_wander_destination(
        world: WorldState,
        agent: AgentState,
        tick: int,
    ) -> tuple[int, int] | None:
        """Choose the first legal adjacent wander tile in a deterministic order."""

        horizontal_preference = [(-1, 0), (1, 0)] if tick % 2 == 1 else [(1, 0), (-1, 0)]
        vertical_preference = [(0, 1), (0, -1)] if _agent_bias(agent) % 2 == 0 else [(0, -1), (0, 1)]

        for delta_x, delta_y in [*horizontal_preference, *vertical_preference]:
            target_x = agent.x + delta_x
            target_y = agent.y + delta_y
            if is_action_legal(world, agent, "move", target_x=target_x, target_y=target_y):
                return target_x, target_y
        return None

    @staticmethod
    def _select_flee_destination(world: WorldState, agent: AgentState) -> tuple[int, int] | None:
        """Choose the farthest immediately legal adjacent tile from nearby threats."""

        legal_moves: list[tuple[int, int]] = []
        for delta_x, delta_y in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            target_x = agent.x + delta_x
            target_y = agent.y + delta_y
            if is_action_legal(world, agent, "move", target_x=target_x, target_y=target_y):
                legal_moves.append((target_x, target_y))

        if not legal_moves:
            return None

        threats = [threat for threat in world.agents if threat.is_threat and threat.alive]
        if not threats:
            return legal_moves[0]

        def score(move: tuple[int, int]) -> tuple[int, int, int]:
            x, y = move
            nearest_threat = min(abs(threat.x - x) + abs(threat.y - y) for threat in threats)
            return (nearest_threat, -y, -x)

        return max(legal_moves, key=score)


def _agent_bias(agent: AgentState) -> int:
    """Derive a stable per-agent bias for deterministic tie-breaking."""

    return sum(ord(character) for character in agent.agent_id)
