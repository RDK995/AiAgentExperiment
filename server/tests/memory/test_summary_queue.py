"""Focused tests for daily-summary queue behavior."""

from __future__ import annotations

from app.db.enums import AgentSex, StageOfLife
from app.engine.world_state import AgentState
from app.memory.summary_queue import DailySummaryQueue
from app.schemas.reflection import MemoryCandidate


def _agent() -> AgentState:
    return AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        sex=AgentSex.FEMALE,
        stage_of_life=StageOfLife.ADULT,
    )


def test_high_salience_candidates_queue_deterministically_per_day() -> None:
    """High-value memory candidates should queue once per day in insertion order."""

    queue = DailySummaryQueue(minimum_salience=0.60)
    agent = _agent()

    first = queue.enqueue(
        agent,
        day_index=100,
        candidate=MemoryCandidate(text="A food source ran dry.", salience=0.72, valence=-0.5),
    )
    duplicate = queue.enqueue(
        agent,
        day_index=100,
        candidate=MemoryCandidate(text="A food source ran dry.", salience=0.90, valence=-0.5),
    )
    second = queue.enqueue(
        agent,
        day_index=100,
        candidate=MemoryCandidate(text="agent-2 gave me berries.", salience=0.81, valence=0.7),
    )

    assert first is True
    assert duplicate is False
    assert second is True
    assert [candidate.text for candidate in agent.daily_summary_candidates] == [
        "A food source ran dry.",
        "agent-2 gave me berries.",
    ]


def test_low_value_candidates_are_skipped_and_day_rollover_resets_queue() -> None:
    """Low-salience noise should be dropped and a new day should reset the queue."""

    queue = DailySummaryQueue(minimum_salience=0.60)
    agent = _agent()

    assert queue.enqueue(
        agent,
        day_index=100,
        candidate=MemoryCandidate(text="Said hello.", salience=0.10, valence=0.1),
    ) is False

    assert queue.enqueue(
        agent,
        day_index=100,
        candidate=MemoryCandidate(text="A proposal was accepted.", salience=0.82, valence=0.8),
    ) is True
    assert queue.enqueue(
        agent,
        day_index=101,
        candidate=MemoryCandidate(text="A child was born.", salience=0.95, valence=0.9),
    ) is True

    assert agent.daily_summary_day_index == 101
    assert [candidate.text for candidate in agent.daily_summary_candidates] == ["A child was born."]
