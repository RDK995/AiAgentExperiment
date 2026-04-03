"""Focused tests for deterministic utility scoring."""

from __future__ import annotations

from app.agents.utility_ai import UtilityAI
from app.agents.perception import PerceptionResult
from app.engine.world_state import AgentState


def test_high_thirst_strongly_favors_drink() -> None:
    """Severe thirst should deterministically dominate the action ranking."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, thirst=80.0)
    perception = PerceptionResult(nearby_water=True)

    top = UtilityAI.select_best_action(agent, perception)

    assert top.action_type.value == "drink"


def test_high_hunger_favors_eat_over_wander() -> None:
    """Severe hunger should promote direct food-seeking behavior."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, hunger=70.0)
    perception = PerceptionResult(nearby_food=True)

    ranked = UtilityAI().score_actions(agent, perception)

    assert ranked[0].action_type.value == "eat"
    assert ranked[0].score > ranked[-1].score


def test_nearby_threat_strongly_favors_flee() -> None:
    """Threat presence should make fleeing the dominant action."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, safety=20.0)
    perception = PerceptionResult(nearby_threat=True)

    top = UtilityAI.select_best_action(agent, perception)

    assert top.action_type.value == "flee"


def test_scoring_is_deterministic_for_same_inputs() -> None:
    """Repeated scoring over the same state should produce the same ordering."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, hunger=20.0, thirst=30.0, fatigue=10.0)
    perception = PerceptionResult(nearby_water=True, nearby_food=False)
    utility = UtilityAI()

    first = utility.score_actions(agent, perception)
    second = utility.score_actions(agent, perception)

    assert [(item.action_type.value, item.score) for item in first] == [
        (item.action_type.value, item.score) for item in second
    ]


def test_high_fatigue_favors_rest() -> None:
    """Severe fatigue should push rest above wandering and most background work."""

    agent = AgentState(agent_id="agent-1", name="A", x=0, y=0, fatigue=85.0)
    perception = PerceptionResult(nearby_bed=True)

    top = UtilityAI.select_best_action(agent, perception)

    assert top.action_type.value == "rest"


def test_planner_hints_create_deterministic_trait_like_scoring_difference() -> None:
    """Planner hints should create a stable scoring difference for otherwise identical agents."""

    baseline = AgentState(agent_id="agent-1", name="A", x=0, y=0, thirst=20.0)
    hinted = AgentState(
        agent_id="agent-2",
        name="B",
        x=0,
        y=0,
        thirst=20.0,
        pending_planner_hints=["drink_soon"],
    )
    perception = PerceptionResult(nearby_water=True)

    baseline_ranked = UtilityAI().score_actions(baseline, perception)
    hinted_ranked = UtilityAI().score_actions(hinted, perception)

    assert baseline_ranked[0].action_type.value == "drink"
    assert hinted_ranked[0].action_type.value == "drink"
    assert hinted_ranked[0].score > baseline_ranked[0].score


def test_childcare_duty_and_visible_infants_favor_care_for_child() -> None:
    """Infant care obligations should strongly promote childcare over ambient actions."""

    agent = AgentState(
        agent_id="agent-1",
        name="Caretaker",
        x=0,
        y=0,
        has_infant_care_duty=True,
    )
    perception = PerceptionResult(nearby_infant_ids=["infant-1"])

    top = UtilityAI.select_best_action(agent, perception)

    assert top.action_type.value == "care_for_child"


def test_daylight_changes_field_work_score_deterministically() -> None:
    """Work-field scoring should be stronger during daylight than at night."""

    agent = AgentState(agent_id="agent-1", name="Farmer", x=0, y=0, hunger=5.0, thirst=5.0, fatigue=5.0)
    daylight = PerceptionResult(sim_hour=10)
    night = PerceptionResult(sim_hour=22)
    utility = UtilityAI()

    daylight_score = next(
        candidate.score
        for candidate in utility.score_actions(agent, daylight)
        if candidate.action_type.value == "work_field"
    )
    night_score = next(
        candidate.score
        for candidate in utility.score_actions(agent, night)
        if candidate.action_type.value == "work_field"
    )

    assert daylight_score > night_score
