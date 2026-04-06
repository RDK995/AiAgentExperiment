"""Authoritative action execution for a single fast-loop step."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from app.agents.actions import ActionType, PlannedTask, SelectedAction, TaskType
from app.agents.perception import PerceptionResult
from app.db.enums import StageOfLife
from app.engine.event_bus import EventBus
from app.engine.rules.simulation_rules import is_action_legal
from app.engine.world_state import AgentState, ResourceNodeState, WorldState
from app.schemas.event import EventType, SimulationEvent
from app.social.bonding import BondingService, RelationshipMetrics


class ActionExecutor:
    """Apply one deterministic action step to authoritative state."""

    def __init__(self, *, bonding_service: BondingService | None = None) -> None:
        self._bonding_service = bonding_service

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
            if not self._consume_inventory_item(agent, {"water"}):
                self._consume_water_source(world, agent)
            agent.thirst = max(0.0, agent.thirst - 10.0)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.AGENT_DRANK,
                domain_payload={"action": "drink"},
            )
        if task.task_type is TaskType.EAT:
            if not self._consume_inventory_item(agent, {"meal", "food", "berries", "fruit", "fish"}):
                food_source_empty = {"value": False}
                self._consume_food_source(world, agent, tick, now, event_bus, events, food_source_empty)
            agent.hunger = max(0.0, agent.hunger - 8.0)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.AGENT_ATE,
                domain_payload={"action": "eat"},
            )
        if task.task_type is TaskType.SLEEP:
            if not self._can_sleep(world, agent):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.fatigue = max(0.0, agent.fatigue - 12.0)
            agent.health = min(100.0, agent.health + 2.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.REST:
            agent.fatigue = max(0.0, agent.fatigue - 6.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.GATHER_BERRIES:
            if not self._gather_resource(world, agent, {"berries"}, inventory_item="berries"):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.FISH:
            if not self._can_fish(world, agent):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.inventory["fish"] = agent.inventory.get("fish", 0) + 1
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.GATHER_FOOD:
            food_source_empty = {"value": False}
            if not self._consume_food_source(world, agent, tick, now, event_bus, events, food_source_empty):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.hunger = max(0.0, agent.hunger - 4.0)
            agent.memories.append("Gathered food nearby.")
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.AGENT_ATE,
                domain_payload={"action": "gather_food", "food_source_empty": food_source_empty["value"]},
            )
        if task.task_type is TaskType.FETCH_WATER:
            if not self._consume_water_source(world, agent):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.inventory["water"] = agent.inventory.get("water", 0) + 1
            agent.thirst = max(0.0, agent.thirst - 4.0)
            agent.memories.append("Fetched fresh water.")
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.AGENT_DRANK,
                domain_payload={"action": "fetch_water"},
            )
        if task.task_type is TaskType.PLANT_CROP:
            if not self._consume_inventory_item(agent, {"seed"}):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            world.resources.append(ResourceNodeState(resource_type="field", x=agent.x, y=agent.y, quantity=1))
            world.crop_growth = max(world.crop_growth, 5.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.HARVEST_CROP:
            if world.crop_growth < 50.0 or not self._gather_resource(world, agent, {"field", "orchard"}, inventory_item="crop"):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.CHOP_WOOD:
            if world.terrain_at(agent.x, agent.y) != "forest":
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.inventory["wood"] = agent.inventory.get("wood", 0) + 1
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.COOK_FOOD:
            if not self._cook_meal(agent):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.COOK:
            agent.hunger = max(0.0, agent.hunger - 5.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.STORE_ITEM:
            item_type = str(task.metadata.get("item_type", "food"))
            if not self._transfer_inventory(agent.inventory, agent.home_inventory, item_type):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.RETRIEVE_ITEM:
            item_type = str(task.metadata.get("item_type", "food"))
            if not self._transfer_inventory(agent.home_inventory, agent.inventory, item_type):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.GREET:
            target = self._resolve_target_agent(world, task)
            if target is None or not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.loneliness = max(0.0, agent.loneliness - 2.0)
            agent.morale = min(100.0, agent.morale + 1.0)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.SOCIAL_MILESTONE,
                domain_payload={"kind": "greet", "target_agent_id": target.agent_id},
            )
        if task.task_type in {TaskType.TALK, TaskType.SOCIALIZE}:
            target = self._resolve_target_agent(world, task)
            if target is not None and not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.loneliness = max(0.0, agent.loneliness - 8.0)
            agent.morale = min(100.0, agent.morale + 2.0)
            payload = {"kind": "talk"}
            if target is not None:
                payload["target_agent_id"] = target.agent_id
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.SOCIAL_MILESTONE,
                domain_payload=payload,
            )
        if task.task_type is TaskType.GIVE_ITEM:
            target = self._resolve_target_agent(world, task)
            item_type = str(task.metadata.get("item_type", "food"))
            if (
                target is None
                or not self._can_interact_with_target(agent, target)
                or not self._transfer_inventory(agent.inventory, target.inventory, item_type)
            ):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.GIFT_GIVEN,
                domain_payload={"item_type": item_type},
            )
        if task.task_type is TaskType.ASK_HELP:
            target = self._resolve_target_agent(world, task)
            if target is None or not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.hope = min(100.0, agent.hope + 1.0)
            target.morale = min(100.0, target.morale + 1.0)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.SOCIAL_MILESTONE,
                domain_payload={"kind": "ask_help", "target_agent_id": target.agent_id},
            )
        if task.task_type is TaskType.INSULT:
            target = self._resolve_target_agent(world, task)
            if target is None or not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.INSULT_SPOKEN,
                domain_payload={"target_agent_id": target.agent_id},
            )
        if task.task_type is TaskType.APOLOGIZE:
            target = self._resolve_target_agent(world, task)
            if target is None or not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.shame = max(0.0, agent.shame - 2.0)
            target.stress = max(0.0, target.stress - 1.0)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.SOCIAL_MILESTONE,
                domain_payload={"kind": "apologize", "target_agent_id": target.agent_id},
            )
        if task.task_type is TaskType.COURT:
            target = self._resolve_target_agent(world, task)
            if target is not None and not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            agent.hope = min(100.0, agent.hope + 2.0)
            payload = {"kind": "court"}
            if target is not None:
                payload["target_agent_id"] = target.agent_id
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.SOCIAL_MILESTONE,
                domain_payload=payload,
            )
        if task.task_type is TaskType.PROPOSE_BOND:
            target = self._resolve_target_agent(world, task)
            if (
                target is None
                or not self._can_interact_with_target(agent, target)
                or self._bonding_service is None
            ):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            result = self._bonding_service.attempt_bond(
                agent,
                target,
                RelationshipMetrics(familiarity=0.8, trust=0.7, attraction=0.8, admiration=0.5),
                RelationshipMetrics(familiarity=0.8, trust=0.7, attraction=0.8, admiration=0.5),
                world=world,
                tick=tick,
                now=now,
                event_bus=event_bus,
            )
            if not result.attempted:
                return self._fail_task(event_bus, tick, now, agent, task, events)
            if result.events:
                events.extend(result.events)
            if not result.accepted:
                return False
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.COMFORT:
            target = self._resolve_target_agent(world, task)
            if target is None or not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            target.grief = max(0.0, target.grief - 3.0)
            target.stress = max(0.0, target.stress - 2.0)
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.SOCIAL_MILESTONE,
                domain_payload={"kind": "comfort", "target_agent_id": target.agent_id},
            )
        if task.task_type is TaskType.MOURN:
            agent.grief = max(0.0, agent.grief - 2.0)
            agent.current_goal = "Honor the dead"
            return self._complete_non_move_task(
                event_bus,
                tick,
                now,
                agent,
                task,
                events,
                domain_event_type=EventType.SOCIAL_MILESTONE,
                domain_payload={"kind": "mourn"},
            )
        if task.task_type in {TaskType.CARE_FOR_INFANT, TaskType.CARE_FOR_CHILD}:
            target = self._resolve_target_agent(world, task)
            if (
                target is None
                or target.stage_of_life not in {StageOfLife.INFANT, StageOfLife.CHILD}
                or not self._can_interact_with_target(agent, target)
            ):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            target.hunger = max(0.0, target.hunger - 4.0)
            target.fatigue = max(0.0, target.fatigue - 4.0)
            agent.stress = max(0.0, agent.stress - 3.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.ESCORT_CHILD:
            target = self._resolve_target_agent(world, task)
            if (
                target is None
                or target.stage_of_life not in {StageOfLife.CHILD, StageOfLife.ADOLESCENT}
                or not self._can_interact_with_target(agent, target)
            ):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            target.safety = min(100.0, target.safety + 5.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.TEACH_SKILL:
            target = self._resolve_target_agent(world, task)
            if target is None or not self._can_interact_with_target(agent, target):
                return self._fail_task(event_bus, tick, now, agent, task, events)
            skill_name = str(task.metadata.get("skill_name", "foraging"))
            target.skills[skill_name] = round(min(5.0, target.skills.get(skill_name, 0.0) + 0.5), 2)
            target.hope = min(100.0, target.hope + 1.0)
            return self._complete_non_move_task(event_bus, tick, now, agent, task, events)
        if task.task_type is TaskType.SHARE_FOOD_HOME:
            shared = self._share_food_home(world, agent)
            if not shared:
                return self._fail_task(event_bus, tick, now, agent, task, events)
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
        domain_event_type: EventType | None = None,
        domain_payload: dict[str, object] | None = None,
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
        if domain_event_type is not None:
            events.append(
                self._emit_event(
                    event_bus,
                    domain_event_type,
                    tick,
                    now,
                    agent,
                    domain_payload or {},
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

    def _consume_food_source(
        self,
        world: WorldState,
        agent: AgentState,
        tick: int,
        now: datetime,
        event_bus: EventBus,
        events: list[SimulationEvent],
        food_source_empty: dict[str, bool],
    ) -> bool:
        """Consume one unit of food from the authoritative world at the agent location."""

        for index, item in enumerate(world.items):
            if (item.x, item.y) == (agent.x, agent.y) and item.item_type in {"food", "berries", "fruit", "meal"}:
                item.quantity -= 1
                if item.quantity <= 0:
                    world.items.pop(index)
                    food_source_empty["value"] = True
                    events.append(
                        self._emit_event(
                            event_bus,
                            EventType.FOOD_STORE_EMPTY,
                            tick,
                            now,
                            agent,
                            {"item_type": item.item_type},
                            location_x=item.x,
                            location_y=item.y,
                        )
                    )
                return True

        for resource in world.resources:
            if (resource.x, resource.y) == (agent.x, agent.y) and resource.resource_type in {"berries", "field", "orchard", "fish"}:
                if resource.quantity <= 0:
                    return False
                resource.quantity = max(0, resource.quantity - 1)
                if resource.quantity == 0:
                    food_source_empty["value"] = True
                    events.append(
                        self._emit_event(
                            event_bus,
                            EventType.FOOD_STORE_EMPTY,
                            tick,
                            now,
                            agent,
                            {"resource_type": resource.resource_type},
                            location_x=resource.x,
                            location_y=resource.y,
                        )
                    )
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

    @staticmethod
    def _consume_inventory_item(agent: AgentState, item_types: Iterable[str]) -> bool:
        for item_type in item_types:
            quantity = agent.inventory.get(item_type, 0)
            if quantity > 0:
                if quantity == 1:
                    agent.inventory.pop(item_type, None)
                else:
                    agent.inventory[item_type] = quantity - 1
                return True
        return False

    @staticmethod
    def _transfer_inventory(source: dict[str, int], destination: dict[str, int], item_type: str) -> bool:
        quantity = source.get(item_type, 0)
        if quantity <= 0:
            return False
        if quantity == 1:
            source.pop(item_type, None)
        else:
            source[item_type] = quantity - 1
        destination[item_type] = destination.get(item_type, 0) + 1
        return True

    @staticmethod
    def _resolve_target_agent(world: WorldState, task: PlannedTask) -> AgentState | None:
        target_agent_id = task.metadata.get("target_agent_id")
        if not isinstance(target_agent_id, str):
            return None
        return world.agent_by_id(target_agent_id)

    @staticmethod
    def _can_interact_with_target(agent: AgentState, target: AgentState) -> bool:
        if not agent.alive or not target.alive:
            return False
        return abs(agent.x - target.x) + abs(agent.y - target.y) <= 1

    @staticmethod
    def _can_sleep(world: WorldState, agent: AgentState) -> bool:
        if "bed" in agent.inventory:
            return True
        if "bed" in agent.home_inventory:
            return True
        return any(item.item_type == "bed" and (item.x, item.y) == (agent.x, agent.y) for item in world.items)

    def _gather_resource(
        self,
        world: WorldState,
        agent: AgentState,
        resource_types: set[str],
        *,
        inventory_item: str,
    ) -> bool:
        for resource in world.resources:
            if (resource.x, resource.y) == (agent.x, agent.y) and resource.resource_type in resource_types:
                if resource.quantity <= 0:
                    return False
                resource.quantity -= 1
                agent.inventory[inventory_item] = agent.inventory.get(inventory_item, 0) + 1
                return True
        return False

    def _can_fish(self, world: WorldState, agent: AgentState) -> bool:
        if self._gather_resource(world, agent, {"fish"}, inventory_item="fish"):
            return True
        return self._consume_water_source(world, agent)

    @staticmethod
    def _cook_meal(agent: AgentState) -> bool:
        for raw_item in ("fish", "crop", "berries", "food"):
            quantity = agent.inventory.get(raw_item, 0)
            if quantity <= 0:
                continue
            if quantity == 1:
                agent.inventory.pop(raw_item, None)
            else:
                agent.inventory[raw_item] = quantity - 1
            agent.inventory["meal"] = agent.inventory.get("meal", 0) + 1
            return True
        return False

    @staticmethod
    def _share_food_home(world: WorldState, agent: AgentState) -> bool:
        if not ActionExecutor._consume_inventory_item(agent, {"meal", "food", "berries", "fish"}):
            return False
        shared = False
        for other in world.agents:
            if other.agent_id == agent.agent_id or other.household_id != agent.household_id:
                continue
            other.hunger = max(0.0, other.hunger - 4.0)
            shared = True
        return shared

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
        *,
        actor_ids: list[str] | None = None,
        target_ids: list[str] | None = None,
        location_x: int | None = None,
        location_y: int | None = None,
        source_module: str = "executor",
    ) -> SimulationEvent:
        """Create, enqueue, and return a simulation event."""

        event = SimulationEvent(
            type=event_type,
            tick=tick,
            sim_time=now,
            agent_id=agent.agent_id,
            actor_ids=list(actor_ids or [agent.agent_id]),
            target_ids=list(target_ids or []),
            location_x=agent.x if location_x is None else location_x,
            location_y=agent.y if location_y is None else location_y,
            source_module=source_module,
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
