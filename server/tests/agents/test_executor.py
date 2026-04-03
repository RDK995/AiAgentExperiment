"""Focused tests for authoritative task execution."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.actions import ActionType, PlannedTask, SelectedAction, TaskType
from app.agents.executor import ActionExecutor
from app.agents.perception import PerceptionResult
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, ItemStackState, ResourceNodeState, TerrainType, TileState, WorldState
from app.schemas.event import EventType


def test_executor_steps_task_queue_and_updates_agent_progress() -> None:
    """Execution should walk a queued plan forward one task at a time."""

    world = _make_world()
    agent = world.agents[0]
    executor = ActionExecutor()
    now = datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc)

    selected = SelectedAction(
        action_type=ActionType.FETCH_WATER,
        tasks=[
            PlannedTask(TaskType.MOVE_TO, target_x=2, target_y=1),
            PlannedTask(TaskType.FETCH_WATER),
            PlannedTask(TaskType.DRINK),
        ],
    )

    first_events = executor.execute(world, agent, selected, tick=1, now=now, event_bus=EventBus())
    second_events = executor.execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.FETCH_WATER, tasks=selected.tasks),
        tick=2,
        now=now,
        event_bus=EventBus(),
    )
    third_events = executor.execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.FETCH_WATER, tasks=selected.tasks),
        tick=3,
        now=now,
        event_bus=EventBus(),
    )

    assert (agent.x, agent.y) == (2, 1)
    assert agent.thirst == 0.0
    assert world.resources == []
    assert any(event.type is EventType.TASK_COMPLETED for event in first_events)
    assert any(event.type is EventType.TASK_COMPLETED for event in second_events)
    assert any(event.type is EventType.ACTION_EXECUTED for event in third_events)


def test_executor_interrupts_previous_task_when_fleeing() -> None:
    """Urgent flee actions should interrupt an in-flight task queue cleanly."""

    world = _make_world()
    agent = world.agents[0]
    agent.task_queue = [PlannedTask(TaskType.GATHER_FOOD).to_payload()]
    agent.current_task_payload = agent.task_queue[0]
    agent.current_action = "gather_food"

    events = ActionExecutor().execute(
        world,
        agent,
        SelectedAction(
            action_type=ActionType.FLEE,
            interrupted_previous_action=True,
            tasks=[PlannedTask(TaskType.FLEE_STEP)],
        ),
        tick=1,
        now=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        event_bus=EventBus(),
    )

    assert agent.current_action == "flee"
    assert any(event.type is EventType.TASK_INTERRUPTED for event in events)
    assert any(event.type is EventType.ACTION_EXECUTED for event in events)


def test_executor_consumes_food_items_from_authoritative_world() -> None:
    """Gather-food execution should deplete item stacks in authoritative state."""

    world = _make_world()
    agent = world.agents[0]
    agent.x = 1
    agent.y = 1
    world.items.append(ItemStackState(item_type="berries", x=1, y=1, quantity=1))

    events = ActionExecutor().execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.GATHER_FOOD, tasks=[PlannedTask(TaskType.GATHER_FOOD)]),
        tick=1,
        now=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        event_bus=EventBus(),
    )

    assert world.items == []
    assert "Gathered food nearby." in agent.memories
    assert any(event.type is EventType.TASK_COMPLETED for event in events)


def test_executor_emits_task_started_and_progress_for_move_tasks() -> None:
    """Movement tasks should emit start and progress events before completion."""

    world = _make_world()
    agent = world.agents[0]

    events = ActionExecutor().execute(
        world,
        agent,
        SelectedAction(
            action_type=ActionType.FETCH_WATER,
            tasks=[PlannedTask(TaskType.MOVE_TO, target_x=2, target_y=1), PlannedTask(TaskType.FETCH_WATER)],
        ),
        tick=1,
        now=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        event_bus=EventBus(),
    )

    assert (agent.x, agent.y) == (2, 1)
    assert any(event.type is EventType.TASK_STARTED for event in events)
    assert any(event.type is EventType.TASK_PROGRESS for event in events)
    assert any(event.type is EventType.TASK_COMPLETED for event in events)


def test_executor_fails_cleanly_when_move_task_is_impossible() -> None:
    """Blocked movement targets should produce a plan failure instead of mutating position."""

    world = WorldState(
        width=2,
        height=1,
        tiles=[
            TileState(x=0, y=0, terrain=TerrainType.GRASS),
            TileState(x=1, y=0, terrain=TerrainType.WATER, walkable=False),
        ],
        agents=[AgentState(agent_id="agent-1", name="A", x=0, y=0)],
    )
    agent = world.agents[0]

    events = ActionExecutor().execute(
        world,
        agent,
        SelectedAction(
            action_type=ActionType.FETCH_WATER,
            tasks=[PlannedTask(TaskType.MOVE_TO, target_x=1, target_y=0)],
        ),
        tick=1,
        now=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        event_bus=EventBus(),
    )

    assert (agent.x, agent.y) == (0, 0)
    assert agent.plan_failure_count == 1
    assert any(event.type is EventType.PLAN_FAILED for event in events)
    assert any(event.type is EventType.ACTION_EXECUTED for event in events)


def test_executor_perception_threat_interrupts_current_plan_into_flee() -> None:
    """Threat perception should override the selected task and execute a flee step immediately."""

    world = _make_world()
    world.agents.append(AgentState(agent_id="threat-1", name="Wolf", x=0, y=1, is_threat=True))
    agent = world.agents[0]
    agent.task_queue = [PlannedTask(TaskType.GATHER_FOOD).to_payload()]
    agent.current_task_payload = agent.task_queue[0]
    agent.current_action = "gather_food"

    events = ActionExecutor().execute(
        world,
        agent,
        SelectedAction(
            action_type=ActionType.GATHER_FOOD,
            interrupted_previous_action=False,
            tasks=[PlannedTask(TaskType.GATHER_FOOD)],
        ),
        tick=1,
        now=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        event_bus=EventBus(),
        perception=PerceptionResult(nearby_threat=True),
    )

    assert agent.current_action == "gather_food"
    assert agent.safety > 0.0
    assert any(event.type is EventType.TASK_COMPLETED for event in events)
    assert any(
        event.type is EventType.TASK_COMPLETED and event.payload.get("task") == "flee_step"
        for event in events
    )


def test_executor_fails_cleanly_when_selected_action_has_no_tasks() -> None:
    """Empty plans should fail deterministically without mutating position."""

    world = _make_world()
    agent = world.agents[0]

    events = ActionExecutor().execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.IDLE, tasks=[]),
        tick=1,
        now=datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
        event_bus=EventBus(),
    )

    assert (agent.x, agent.y) == (1, 1)
    assert agent.plan_failure_count == 1
    assert any(event.type is EventType.PLAN_FAILED for event in events)
    assert any(event.type is EventType.ACTION_EXECUTED for event in events)


def _make_world() -> WorldState:
    """Build a compact deterministic world for executor tests."""

    return WorldState(
        width=3,
        height=3,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(3)],
        agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1, thirst=4.0)],
        resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=1)],
    )
