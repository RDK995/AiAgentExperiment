"""Focused tests for memory retrieval with daily-summary integration."""

from __future__ import annotations

from app.db.enums import AgentSex, StageOfLife
from app.engine.world_state import AgentState
from app.memory.retriever import MemoryRetriever
from app.schemas.reflection import MemoryCandidate


def test_retriever_prioritizes_high_salience_daily_summary_candidates() -> None:
    """Daily-summary candidates should lead retrieval order for slow-loop context."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        sex=AgentSex.FEMALE,
        stage_of_life=StageOfLife.ADULT,
        memories=[
            "Met a neighbor.",
            "Gathered food nearby.",
            "Shared a meal.",
            "Slept well.",
        ],
        daily_summary_candidates=[
            MemoryCandidate(text="A food source ran dry.", salience=0.72, valence=-0.5),
            MemoryCandidate(text="agent-2 gave me berries.", salience=0.91, valence=0.7),
        ],
    )

    retrieved = MemoryRetriever().retrieve_recent_events(agent)

    assert retrieved[:2] == [
        "agent-2 gave me berries.",
        "A food source ran dry.",
    ]
    assert "Shared a meal." in retrieved


def test_retriever_deduplicates_summary_candidates_against_recent_memories() -> None:
    """The same memory text should not appear twice when queued and already persisted in memory."""

    agent = AgentState(
        agent_id="agent-1",
        name="A",
        x=0,
        y=0,
        sex=AgentSex.FEMALE,
        stage_of_life=StageOfLife.ADULT,
        memories=[
            "A proposal was accepted.",
            "Worked in the field.",
            "A proposal was accepted.",
        ],
        daily_summary_candidates=[
            MemoryCandidate(text="A proposal was accepted.", salience=0.82, valence=0.8),
        ],
    )

    retrieved = MemoryRetriever().retrieve_recent_events(agent)

    assert retrieved.count("A proposal was accepted.") == 1
    assert len(retrieved) <= 5
