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
        "retrieve_item",
        "move_to",
        "cook_food",
        "share_food_home",
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
        ("care_for_infant", None, None),
    ]
    assert tasks[1].metadata["target_agent_id"] == "infant-1"


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


def test_partner_visit_hint_biases_social_plans_and_targets_partner() -> None:
    """Partner-oriented hints should bias action choice and annotate the legal social task."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        partner_id="agent-2",
        pending_planner_hints=["visit_partner"],
    )
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[
            ActionCandidate(action_type=ActionType.WANDER, score=15.0),
            ActionCandidate(action_type=ActionType.SOCIALIZE, score=15.0),
        ],
        perception=PerceptionResult(visible_agents=["agent-2"], visible_partner=True),
    )

    assert selected.action_type.value == "socialize"
    assert [task.task_type.value for task in selected.tasks] == ["greet", "talk"]
    assert selected.tasks[0].metadata["target_agent_id"] == "agent-2"
    assert selected.tasks[1].metadata["target_agent_id"] == "agent-2"
    assert "visit_partner" in selected.tasks[0].metadata["planner_hints"]


def test_avoid_agent_hint_penalizes_social_plans_when_target_is_visible() -> None:
    """Avoidance hints should steer tied plans away from social contact with the avoided agent."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        pending_planner_hints=["avoid_agent_agent-2"],
    )
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[
            ActionCandidate(action_type=ActionType.SOCIALIZE, score=18.0),
            ActionCandidate(action_type=ActionType.WANDER, score=18.0),
        ],
        perception=PerceptionResult(visible_agents=["agent-2"]),
    )

    assert selected.action_type.value == "wander"
    assert "avoid_agent_agent-2" in selected.tasks[0].metadata["planner_hints"]
    assert selected.tasks[0].metadata["avoid_agent_ids"] == ["agent-2"]


def test_prepare_for_winter_hint_biases_work_toward_resource_security() -> None:
    """Seasonal preparation hints should favor legal field/resource work over idle exploration."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        pending_planner_hints=["prepare_for_winter"],
    )
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[
            ActionCandidate(action_type=ActionType.WANDER, score=15.0),
            ActionCandidate(action_type=ActionType.WORK_FIELD, score=15.0),
        ],
        perception=PerceptionResult(sim_hour=10),
    )

    assert selected.action_type.value == "work_field"
    assert "prepare_for_winter" in selected.tasks[0].metadata["planner_hints"]


def test_prioritize_food_security_biases_tied_plans_toward_legal_food_security_action() -> None:
    """Food-security hints should prefer a legal food-oriented plan when options are otherwise tied."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        pending_planner_hints=["prioritize_food_security"],
    )
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[
            ActionCandidate(action_type=ActionType.WANDER, score=15.0),
            ActionCandidate(action_type=ActionType.GATHER_FOOD, score=15.0),
        ],
        perception=PerceptionResult(nearest_food_x=2, nearest_food_y=1, nearby_food=True),
    )

    assert selected.action_type.value == "gather_food"
    assert [task.task_type.value for task in selected.tasks] == ["move_to", "gather_food", "eat"]
    assert selected.tasks[0].metadata["label"] == "food"
    assert "prioritize_food_security" in selected.tasks[0].metadata["planner_hints"]


def test_socialize_maps_to_concrete_social_tasks_with_visible_target() -> None:
    """Social objectives should expand into concrete greeting/talk tasks with a deterministic target."""

    tasks = ActionPlanner().plan_objective(
        "socialize",
        AgentState(agent_id="agent-1", name="A", x=0, y=0, partner_id="agent-3"),
        PerceptionResult(visible_agents=["agent-2", "agent-3"], visible_partner=True),
    )

    assert [task.task_type.value for task in tasks] == ["greet", "talk"]
    assert tasks[0].metadata["target_agent_id"] == "agent-3"
    assert tasks[1].metadata["target_agent_id"] == "agent-3"


def test_gather_food_prefers_berries_when_visible_over_generic_food_task() -> None:
    """Food gathering should choose the more concrete berry action when berry resources are present."""

    tasks = ActionPlanner().plan_objective(
        "gather_food",
        AgentState(agent_id="agent-1", name="A", x=0, y=0),
        PerceptionResult(nearest_food_x=1, nearest_food_y=0, visible_resources=["berries"], nearby_food=True),
    )

    assert [task.task_type.value for task in tasks] == ["move_to", "gather_berries", "eat"]


def test_focus_on_recovery_biases_tied_plans_toward_legal_rest_without_bypassing_legality() -> None:
    """Recovery hints should prefer legal rest behavior and not synthesize movement commands."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        pending_planner_hints=["focus_on_recovery"],
    )
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[
            ActionCandidate(action_type=ActionType.WANDER, score=15.0),
            ActionCandidate(action_type=ActionType.REST, score=15.0),
        ],
        perception=PerceptionResult(),
    )

    assert selected.action_type.value == "rest"
    assert [task.task_type.value for task in selected.tasks] == ["rest"]
    assert selected.tasks[0].metadata["planner_hints"] == ["focus_on_recovery"]
    assert selected.tasks[0].target_x is None
    assert selected.tasks[0].target_y is None


def test_stay_close_to_home_biases_tied_plans_toward_local_rest_plan() -> None:
    """Home-oriented hints should favor simple local plans over wandering when scores are tied."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        pending_planner_hints=["stay_close_to_home"],
    )
    selected = ActionPlanner().choose_action(
        agent,
        candidates=[
            ActionCandidate(action_type=ActionType.WANDER, score=15.0),
            ActionCandidate(action_type=ActionType.REST, score=15.0),
        ],
        perception=PerceptionResult(),
    )

    assert selected.action_type.value == "rest"
    assert [task.task_type.value for task in selected.tasks] == ["rest"]
    assert selected.tasks[0].metadata["planner_hints"] == ["stay_close_to_home"]
