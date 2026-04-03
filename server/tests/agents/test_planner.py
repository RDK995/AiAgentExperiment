"""Focused tests for rule-based action planning."""

from __future__ import annotations

from app.agents.actions import ActionCandidate, ActionType
from app.agents.planner import ActionPlanner
from app.agents.perception import PerceptionResult
from app.engine.world_state import AgentState


def test_feed_household_maps_to_sensible_task_chain() -> None:
    """Household-feeding objectives should expand into a stable ordered task chain."""

    tasks = ActionPlanner().plan_objective("feed_household", AgentState(agent_id="agent-1", name="A", x=0, y=0))

    assert [task.task_type.value for task in tasks] == [
        "move_to",
        "inspect_stock",
        "gather_food",
        "move_to",
        "cook",
        "distribute_food",
    ]


def test_flee_maps_to_urgent_escape_task() -> None:
    """The flee objective should collapse into a single urgent escape step."""

    tasks = ActionPlanner().plan_objective("flee", AgentState(agent_id="agent-1", name="A", x=0, y=0))

    assert [task.task_type.value for task in tasks] == ["flee_step"]


def test_unsupported_objective_falls_back_to_wander() -> None:
    """Unsupported objectives should degrade cleanly into a deterministic fallback."""

    tasks = ActionPlanner().plan_objective("unknown_objective", AgentState(agent_id="agent-1", name="A", x=0, y=0))

    assert [task.task_type.value for task in tasks] == ["wander_step"]


def test_gather_food_uses_compact_perception_target_when_available() -> None:
    """Resource-seeking plans should prepend a move task when perception exposes a target."""

    tasks = ActionPlanner().plan_objective(
        "gather_food",
        AgentState(agent_id="agent-1", name="A", x=0, y=0),
        PerceptionResult(nearest_food_x=2, nearest_food_y=1),
    )

    assert [(task.task_type.value, task.target_x, task.target_y) for task in tasks] == [
        ("move_to", 2, 1),
        ("gather_food", None, None),
        ("eat", None, None),
    ]


def test_care_for_child_moves_to_visible_infant_before_care() -> None:
    """Childcare plans should honor the compact infant target from perception."""

    tasks = ActionPlanner().plan_objective(
        "care_for_child",
        AgentState(agent_id="agent-1", name="A", x=3, y=3),
        PerceptionResult(nearest_infant_x=2, nearest_infant_y=3, nearby_infant_ids=["infant-1"]),
    )

    assert [(task.task_type.value, task.target_x, task.target_y) for task in tasks] == [
        ("move_to", 2, 3),
        ("care_for_child", None, None),
    ]


def test_drink_plan_outputs_executor_compatible_structured_tasks() -> None:
    """Planned tasks should serialize cleanly into the executor-facing payload shape."""

    tasks = ActionPlanner().plan_objective(
        "drink",
        AgentState(agent_id="agent-1", name="A", x=0, y=0),
        PerceptionResult(nearest_water_x=1, nearest_water_y=0),
    )

    assert [task.task_type.value for task in tasks] == ["move_to", "fetch_water", "drink"]
    assert tasks[0].to_payload() == {
        "task_type": "move_to",
        "target_x": 1,
        "target_y": 0,
        "metadata": {"label": "water"},
    }


def test_drink_plan_skips_move_when_agent_is_already_at_target() -> None:
    """Direct interaction plans should not emit redundant move tasks when already positioned."""

    tasks = ActionPlanner().plan_objective(
        "drink",
        AgentState(agent_id="agent-1", name="A", x=1, y=0),
        PerceptionResult(nearest_water_x=1, nearest_water_y=0),
    )

    assert [task.task_type.value for task in tasks] == ["fetch_water", "drink"]


def test_choose_action_preserves_current_action_without_interrupt_when_top_choice_matches() -> None:
    """Planner should keep continuity when the best action is already in progress."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, current_action="rest")
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[ActionCandidate(action_type=ActionType.REST, score=99.0)],
        perception=PerceptionResult(),
    )

    assert selected.interrupted_previous_action is False
    assert selected.action_type.value == "rest"


def test_choose_action_marks_interrupt_when_best_action_changes() -> None:
    """Planner should explicitly mark action switches as interrupts."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, current_action="gather_food")
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[ActionCandidate(action_type=ActionType.DRINK, score=99.0)],
        perception=PerceptionResult(),
    )

    assert selected.interrupted_previous_action is True
    assert selected.action_type.value == "drink"
