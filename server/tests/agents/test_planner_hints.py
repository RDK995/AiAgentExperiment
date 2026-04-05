"""Focused tests for planner-hint normalization and interpretation."""

from __future__ import annotations

import pytest

from app.agents.actions import ActionCandidate, ActionType
from app.agents.planner_hints import consume_planner_hints_for_action, normalize_planner_hints, rerank_candidates_with_hints
from app.agents.perception import PerceptionResult
from app.engine.world_state import AgentState, WorldState


def _world() -> WorldState:
    return WorldState(
        width=3,
        height=1,
        agents=[
            AgentState(agent_id="agent-1", name="Ari", x=0, y=0, partner_id="agent-2"),
            AgentState(agent_id="agent-2", name="Cara", x=1, y=0, partner_id="agent-1"),
        ],
    )


def test_normalize_planner_hints_maps_supported_intentions_to_canonical_values() -> None:
    """Reflection intentions should normalize into compact planner-facing hints."""

    world = _world()
    normalized = normalize_planner_hints(
        [
            "spend_more_time_with_partner",
            "prioritize_food_security",
            "focus_on_recovery",
            "stay_close_to_home",
        ],
        agent=world.agents[0],
        world=world,
    )

    assert normalized == [
        "visit_partner",
        "prioritize_food_security",
        "focus_on_recovery",
        "stay_close_to_home",
    ]


def test_normalize_planner_hints_rejects_unsupported_intentions_safely() -> None:
    """Unsupported planner intentions should fail safely during normalization."""

    world = _world()

    with pytest.raises(ValueError, match="Unsupported planner hint"):
        normalize_planner_hints(["build_a_castle_tomorrow"], agent=world.agents[0], world=world)


def test_normalize_planner_hints_deduplicates_and_preserves_first_seen_order_deterministically() -> None:
    """Normalization should remain deterministic when repeated aliases point at the same canonical hint."""

    world = _world()

    normalized = normalize_planner_hints(
        [
            "spend_more_time_with_partner",
            "visit_partner",
            "prioritize_food_security",
            "prioritize_food_security",
            "focus_on_recovery",
            "stay_close_to_home",
            "focus_on_recovery",
        ],
        agent=world.agents[0],
        world=world,
    )

    assert normalized == [
        "visit_partner",
        "prioritize_food_security",
        "focus_on_recovery",
        "stay_close_to_home",
    ]


def test_normalize_planner_hints_accepts_targeted_avoidance_by_agent_id() -> None:
    """Explicit agent-id avoidance hints should normalize cleanly when the target exists."""

    world = _world()

    normalized = normalize_planner_hints(
        ["avoid_agent_agent-2"],
        agent=world.agents[0],
        world=world,
    )

    assert normalized == ["avoid_agent_agent-2"]


def test_rerank_candidates_with_hints_preserves_legality_and_noops_unknown_stored_hints() -> None:
    """Hint interpretation should only rerank provided legal candidates and ignore unknown stored strings."""

    agent = AgentState(
        agent_id="agent-1",
        name="Ari",
        x=0,
        y=0,
        pending_planner_hints=["unsupported_hint", "stay_close_to_home"],
    )
    candidates = [
        ActionCandidate(action_type=ActionType.WANDER, score=15.0),
        ActionCandidate(action_type=ActionType.REST, score=15.0),
    ]

    reranked = rerank_candidates_with_hints(agent, candidates, PerceptionResult())

    assert [candidate.action_type.value for candidate in reranked] == ["rest", "wander"]
    assert {candidate.action_type for candidate in reranked} == {ActionType.WANDER, ActionType.REST}


def test_consume_planner_hints_removes_only_the_matching_hint_and_keeps_others() -> None:
    """Hint lifecycle should consume just one applicable hint after a matching legal action."""

    remaining = consume_planner_hints_for_action(
        ["focus_on_recovery", "prioritize_food_security", "stay_close_to_home"],
        selected_action="rest",
        perception=PerceptionResult(),
    )

    assert remaining == ["prioritize_food_security", "stay_close_to_home"]


def test_consume_planner_hints_leaves_queue_unchanged_when_action_does_not_match() -> None:
    """Non-matching legal actions should not accidentally clear unrelated hints."""

    remaining = consume_planner_hints_for_action(
        ["prioritize_food_security", "stay_close_to_home"],
        selected_action="socialize",
        perception=PerceptionResult(visible_agents=["agent-2"]),
    )

    assert remaining == ["prioritize_food_security", "stay_close_to_home"]


def test_consume_planner_hints_removes_stored_alias_token_without_requiring_canonical_value() -> None:
    """Legacy stored aliases should be consumed safely when they match a selected legal action."""

    remaining = consume_planner_hints_for_action(
        ["spend_more_time_with_partner", "prioritize_food_security"],
        selected_action="socialize",
        perception=PerceptionResult(visible_agents=["agent-2"]),
    )

    assert remaining == ["prioritize_food_security"]
