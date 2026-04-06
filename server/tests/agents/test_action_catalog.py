"""Focused tests for the initial v1 action catalog."""

from __future__ import annotations

from datetime import datetime, timezone

from app.agents.actions import ActionType, PlannedTask, SelectedAction, TaskType
from app.agents.executor import ActionExecutor
from app.agents.planner import ActionPlanner
from app.agents.perception import PerceptionResult
from app.db.enums import AgentSex, StageOfLife
from app.engine.event_bus import EventBus
from app.engine.world_state import AgentState, ItemStackState, ResourceNodeState, TerrainType, TileState, WorldState
from app.schemas.event import EventType
from app.social.bonding import BondingService


def test_planner_maps_new_catalog_objectives_into_executor_tasks() -> None:
    """New v1 objectives should expand into deterministic executor-compatible tasks."""

    planner = ActionPlanner()
    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0)

    berry_tasks = planner.plan_objective(
        "gather_berries",
        agent,
        PerceptionResult(nearest_food_x=2, nearest_food_y=0),
    )
    infant_tasks = planner.plan_objective(
        "care_for_infant",
        agent,
        PerceptionResult(nearest_infant_x=1, nearest_infant_y=0, nearby_infant_ids=["infant-1"]),
    )

    assert [task.task_type.value for task in planner.plan_objective("sleep", agent)] == ["sleep"]
    assert [task.task_type.value for task in berry_tasks] == ["move_to", "gather_berries"]
    assert [task.task_type.value for task in planner.plan_objective("propose_bond", agent)] == ["propose_bond"]
    assert [task.task_type.value for task in infant_tasks] == ["move_to", "care_for_infant"]
    assert [task.task_type.value for task in planner.plan_objective("share_food_home", agent)] == ["share_food_home"]


def test_sleep_recovers_more_than_rest_and_requires_a_bed() -> None:
    """Sleep should be a stronger recovery action than rest, with a simple legality gate."""

    world = _make_world()
    agent = world.agents[0]
    agent.fatigue = 30.0
    agent.inventory["bed"] = 1
    now = _now()

    ActionExecutor().execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.SLEEP, tasks=[PlannedTask(TaskType.SLEEP)]),
        tick=1,
        now=now,
        event_bus=EventBus(),
    )
    slept_fatigue = agent.fatigue

    agent.fatigue = 30.0
    ActionExecutor().execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.REST, tasks=[PlannedTask(TaskType.REST)]),
        tick=2,
        now=now,
        event_bus=EventBus(),
    )

    assert slept_fatigue == 18.0
    assert agent.fatigue == 24.0

    agent.inventory.clear()
    world.items.clear()
    agent.fatigue = 30.0
    events = ActionExecutor().execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.SLEEP, tasks=[PlannedTask(TaskType.SLEEP)]),
        tick=3,
        now=now,
        event_bus=EventBus(),
    )

    assert agent.fatigue == 30.0
    assert any(event.type is EventType.PLAN_FAILED for event in events)


def test_work_actions_update_inventory_and_world_resources() -> None:
    """Gathering, fishing, storing, retrieving, and cooking should mutate authoritative state safely."""

    world = _make_world()
    agent = world.agents[0]
    agent.x = 1
    agent.y = 1
    agent.inventory["seed"] = 1
    world.resources.extend(
        [
            ResourceNodeState(resource_type="berries", x=1, y=1, quantity=2),
            ResourceNodeState(resource_type="fish", x=2, y=1, quantity=1),
        ]
    )
    executor = ActionExecutor()
    now = _now()

    executor.execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.GATHER_BERRIES, tasks=[PlannedTask(TaskType.GATHER_BERRIES)]),
        tick=1,
        now=now,
        event_bus=EventBus(),
    )
    agent.x = 2
    agent.y = 1
    executor.execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.FISH, tasks=[PlannedTask(TaskType.FISH)]),
        tick=2,
        now=now,
        event_bus=EventBus(),
    )
    agent.x = 1
    agent.y = 1
    executor.execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.PLANT_CROP, tasks=[PlannedTask(TaskType.PLANT_CROP)]),
        tick=3,
        now=now,
        event_bus=EventBus(),
    )
    world.crop_growth = 80.0
    executor.execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.HARVEST_CROP, tasks=[PlannedTask(TaskType.HARVEST_CROP)]),
        tick=4,
        now=now,
        event_bus=EventBus(),
    )
    agent.inventory["berries"] = agent.inventory.get("berries", 0) + 1
    executor.execute(
        world,
        agent,
        SelectedAction(action_type=ActionType.COOK_FOOD, tasks=[PlannedTask(TaskType.COOK_FOOD)]),
        tick=5,
        now=now,
        event_bus=EventBus(),
    )
    executor.execute(
        world,
        agent,
        SelectedAction(
            action_type=ActionType.STORE_ITEM,
            tasks=[PlannedTask(TaskType.STORE_ITEM, metadata={"item_type": "meal"})],
        ),
        tick=6,
        now=now,
        event_bus=EventBus(),
    )
    executor.execute(
        world,
        agent,
        SelectedAction(
            action_type=ActionType.RETRIEVE_ITEM,
            tasks=[PlannedTask(TaskType.RETRIEVE_ITEM, metadata={"item_type": "meal"})],
        ),
        tick=7,
        now=now,
        event_bus=EventBus(),
    )

    assert agent.inventory["berries"] >= 1
    assert agent.inventory["fish"] >= 1
    assert agent.inventory["crop"] >= 1
    assert agent.inventory["meal"] >= 1
    assert agent.home_inventory == {}
    assert any(resource.resource_type == "field" for resource in world.resources)


def test_social_actions_transfer_items_emit_events_and_form_bonds() -> None:
    """Social tasks should mutate safe actor/target state and reuse the bonding service."""

    world = _make_social_world()
    actor = world.agent_by_id("agent-1")
    target = world.agent_by_id("agent-2")
    assert actor is not None and target is not None
    actor.inventory["berries"] = 1
    executor = ActionExecutor(bonding_service=BondingService())
    bus = EventBus()
    now = _now()

    gift_events = executor.execute(
        world,
        actor,
        SelectedAction(
            action_type=ActionType.GIVE_ITEM,
            tasks=[PlannedTask(TaskType.GIVE_ITEM, metadata={"target_agent_id": "agent-2", "item_type": "berries"})],
        ),
        tick=1,
        now=now,
        event_bus=bus,
    )
    insult_events = executor.execute(
        world,
        actor,
        SelectedAction(
            action_type=ActionType.INSULT,
            tasks=[PlannedTask(TaskType.INSULT, metadata={"target_agent_id": "agent-2"})],
        ),
        tick=2,
        now=now,
        event_bus=bus,
    )
    bond_events = executor.execute(
        world,
        actor,
        SelectedAction(
            action_type=ActionType.PROPOSE_BOND,
            tasks=[PlannedTask(TaskType.PROPOSE_BOND, metadata={"target_agent_id": "agent-2"})],
        ),
        tick=3,
        now=now,
        event_bus=bus,
    )

    assert actor.inventory.get("berries", 0) == 0
    assert target.inventory["berries"] == 1
    assert any(event.type is EventType.GIFT_GIVEN for event in gift_events)
    assert any(event.type is EventType.INSULT_SPOKEN for event in insult_events)
    assert actor.partner_id == "agent-2"
    assert target.partner_id == "agent-1"
    assert any(event.type is EventType.PROPOSAL_MADE for event in bond_events)
    assert any(event.type is EventType.PROPOSAL_ACCEPTED for event in bond_events)


def test_social_action_legality_blocks_distant_targets_without_corrupting_state() -> None:
    """Executor should fail social tasks cleanly when the target is not legally interactable."""

    world = _make_social_world()
    actor = world.agent_by_id("agent-1")
    target = world.agent_by_id("agent-2")
    assert actor is not None and target is not None
    actor.inventory["berries"] = 1
    target.x = 2
    target.y = 2

    events = ActionExecutor().execute(
        world,
        actor,
        SelectedAction(
            action_type=ActionType.GIVE_ITEM,
            tasks=[PlannedTask(TaskType.GIVE_ITEM, metadata={"target_agent_id": "agent-2", "item_type": "berries"})],
        ),
        tick=1,
        now=_now(),
        event_bus=EventBus(),
    )

    assert actor.inventory["berries"] == 1
    assert target.inventory == {}
    assert any(event.type is EventType.PLAN_FAILED for event in events)


def test_family_actions_support_infants_children_and_household_food_sharing() -> None:
    """Family tasks should update dependent state without inventing client-visible authority."""

    world = _make_family_world()
    parent = world.agent_by_id("agent-1")
    infant = world.agent_by_id("infant-1")
    child = world.agent_by_id("child-1")
    sibling = world.agent_by_id("agent-2")
    assert parent is not None and infant is not None and child is not None and sibling is not None
    parent.inventory["food"] = 1
    executor = ActionExecutor()

    executor.execute(
        world,
        parent,
        SelectedAction(
            action_type=ActionType.CARE_FOR_INFANT,
            tasks=[PlannedTask(TaskType.CARE_FOR_INFANT, metadata={"target_agent_id": "infant-1"})],
        ),
        tick=1,
        now=_now(),
        event_bus=EventBus(),
    )
    executor.execute(
        world,
        parent,
        SelectedAction(
            action_type=ActionType.TEACH_SKILL,
            tasks=[PlannedTask(TaskType.TEACH_SKILL, metadata={"target_agent_id": "child-1", "skill_name": "foraging"})],
        ),
        tick=2,
        now=_now(),
        event_bus=EventBus(),
    )
    executor.execute(
        world,
        parent,
        SelectedAction(action_type=ActionType.SHARE_FOOD_HOME, tasks=[PlannedTask(TaskType.SHARE_FOOD_HOME)]),
        tick=3,
        now=_now(),
        event_bus=EventBus(),
    )

    assert infant.hunger == 12.0
    assert infant.fatigue == 12.0
    assert child.skills["foraging"] == 0.5
    assert sibling.hunger == 26.0
    assert "food" not in parent.inventory


def _make_world() -> WorldState:
    return WorldState(
        width=4,
        height=4,
        tiles=[
            TileState(x=x, y=y, terrain=TerrainType.FOREST if (x, y) == (3, 1) else TerrainType.GRASS)
            for y in range(4)
            for x in range(4)
        ],
        agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1, thirst=10.0)],
        items=[ItemStackState(item_type="bed", x=1, y=1, quantity=1)],
        resources=[ResourceNodeState(resource_type="water", x=2, y=1, quantity=2)],
    )


def _make_social_world() -> WorldState:
    return WorldState(
        width=3,
        height=3,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(3)],
        agents=[
            AgentState(agent_id="agent-1", name="A", x=1, y=1, stage_of_life=StageOfLife.ADULT, sex=AgentSex.FEMALE),
            AgentState(agent_id="agent-2", name="B", x=1, y=2, stage_of_life=StageOfLife.ADULT, sex=AgentSex.MALE),
        ],
    )


def _make_family_world() -> WorldState:
    return WorldState(
        width=3,
        height=3,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(3)],
        agents=[
            AgentState(agent_id="agent-1", name="Parent", x=1, y=1, household_id="house-1", stress=10.0),
            AgentState(agent_id="agent-2", name="Sibling", x=1, y=2, household_id="house-1", hunger=30.0),
            AgentState(
                agent_id="infant-1",
                name="Infant",
                x=1,
                y=1,
                household_id="house-1",
                stage_of_life=StageOfLife.INFANT,
                hunger=20.0,
                fatigue=16.0,
            ),
            AgentState(
                agent_id="child-1",
                name="Child",
                x=1,
                y=1,
                household_id="house-1",
                stage_of_life=StageOfLife.CHILD,
            ),
        ],
    )


def _now() -> datetime:
    return datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc)
