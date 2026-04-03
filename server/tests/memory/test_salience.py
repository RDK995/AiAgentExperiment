"""Focused tests for deterministic memory salience scoring."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.enums import AgentSex, StageOfLife
from app.engine.world_state import AgentState
from app.memory.salience import EventSalienceScorer
from app.schemas.event import EventType, SimulationEvent


def _agent(**overrides) -> AgentState:
    return AgentState(
        agent_id="agent-1",
        name="A",
        x=1,
        y=1,
        sex=AgentSex.FEMALE,
        stage_of_life=StageOfLife.ADULT,
        **overrides,
    )


def _event(event_type: EventType, **payload) -> SimulationEvent:
    return SimulationEvent(
        type=event_type,
        tick=10,
        sim_time=datetime(2000, 1, 1, 9, 0, tzinfo=timezone.utc),
        actor_ids=["agent-1"],
        payload=payload,
    )


def test_known_event_types_get_expected_base_weight_ordering() -> None:
    """Death and childbirth should outrank routine consumption events."""

    scorer = EventSalienceScorer()

    death = scorer.components_for(_event(EventType.AGENT_DIED)).base_event_weight
    birth = scorer.components_for(_event(EventType.CHILD_BORN)).base_event_weight
    gift = scorer.components_for(_event(EventType.GIFT_GIVEN)).base_event_weight
    ate = scorer.components_for(_event(EventType.AGENT_ATE)).base_event_weight

    assert death == pytest.approx(1.0)
    assert birth == pytest.approx(0.95)
    assert gift == pytest.approx(0.65)
    assert ate == pytest.approx(0.20)
    assert death > birth > gift > ate


def test_salience_bonuses_change_score_in_sensible_deterministic_ways() -> None:
    """Partner/social/survival context should increase salience deterministically."""

    scorer = EventSalienceScorer()
    agent = _agent(partner_id="agent-2", hunger=90.0)
    event = SimulationEvent(
        type=EventType.GIFT_GIVEN,
        tick=10,
        sim_time=datetime(2000, 1, 1, 9, 0, tzinfo=timezone.utc),
        actor_ids=["agent-2"],
        target_ids=["agent-1"],
        payload={"target_was_starving": True},
    )

    first = scorer.score(event, agent=agent)
    second = scorer.score(event, agent=agent)

    assert first == pytest.approx(second)
    assert first > 0.90


def test_repeated_familiar_event_loses_novelty_bonus() -> None:
    """Recently remembered events should lose the novelty component."""

    scorer = EventSalienceScorer()
    novel_agent = _agent(memories=[])
    familiar_agent = _agent(memories=["I gave berries to agent-2."])
    event = SimulationEvent(
        type=EventType.GIFT_GIVEN,
        tick=10,
        sim_time=datetime(2000, 1, 1, 9, 0, tzinfo=timezone.utc),
        actor_ids=["agent-1"],
        target_ids=["agent-2"],
        payload={"item_type": "berries"},
    )

    novel = scorer.components_for(event, agent=novel_agent)
    familiar = scorer.components_for(event, agent=familiar_agent)

    assert novel.novelty_bonus == pytest.approx(0.10)
    assert familiar.novelty_bonus == pytest.approx(0.0)
    assert novel.total > familiar.total


def test_salience_is_clamped_to_supported_bounds() -> None:
    """Even highly weighted events should remain within the expected [0, 1] range."""

    scorer = EventSalienceScorer()
    agent = _agent(partner_id="agent-2", hunger=99.0, memories=[])
    event = SimulationEvent(
        type=EventType.AGENT_DIED,
        tick=10,
        sim_time=datetime(2000, 1, 1, 9, 0, tzinfo=timezone.utc),
        actor_ids=["agent-2"],
        target_ids=["agent-1"],
        payload={"target_was_starving": True},
    )

    score = scorer.score(event, agent=agent)

    assert score == pytest.approx(1.0)


def test_partner_and_survival_context_raise_salience_relative_to_neutral_context() -> None:
    """The same event should score higher when the agent is hungry and socially invested."""

    scorer = EventSalienceScorer()
    neutral_agent = _agent()
    invested_agent = _agent(partner_id="agent-2", hunger=92.0)
    event = SimulationEvent(
        type=EventType.GIFT_GIVEN,
        tick=11,
        sim_time=datetime(2000, 1, 1, 9, 1, tzinfo=timezone.utc),
        actor_ids=["agent-2"],
        target_ids=["agent-1"],
        payload={},
    )

    neutral_score = scorer.score(event, agent=neutral_agent)
    invested_score = scorer.score(event, agent=invested_agent)

    assert invested_score > neutral_score
