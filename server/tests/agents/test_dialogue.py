"""Focused tests for dialogue preparation built on shared retrieval context."""

from __future__ import annotations

from app.agents.dialogue import DialoguePreparationService
from app.engine.world_state import AgentState
from app.schemas.memory import (
    RetrievalContextResult,
    RetrievedGoalRecord,
    RetrievedMemoryRecord,
    RetrievedRelationshipRecord,
)


def _runtime_agent() -> AgentState:
    return AgentState(
        agent_id="agent-1",
        name="Ari",
        x=1,
        y=1,
        current_goal="Maintain daily routine",
    )


def test_dialogue_preparation_uses_retrieved_context_and_keeps_it_compact() -> None:
    """Dialogue preparation should reuse retrieval results and cap downstream context."""

    class StubRetrievalService:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def retrieve_context(self, agent: AgentState, *, query_text: str) -> RetrievalContextResult:
            self.calls.append((agent.agent_id, query_text))
            return RetrievalContextResult(
                summary="Ari keeps careful records of village life.",
                goals=[
                    RetrievedGoalRecord(title=f"goal-{index}", priority=float(5 - index), status="active")
                    for index in range(5)
                ],
                relationships=[
                    RetrievedRelationshipRecord(
                        related_agent_id=f"agent-{index}",
                        score=float(10 - index),
                        trust=1.0,
                        admiration=0.8,
                        familiarity=0.7,
                        attraction=0.2,
                        obligation=0.3,
                        resentment=0.0,
                        fear=0.0,
                        dependency=0.0,
                        last_interaction_tick=20 - index,
                    )
                    for index in range(2, 7)
                ],
                memories=[
                    RetrievedMemoryRecord(
                        id=f"memory-{index}",
                        raw_text=f"memory-{index}",
                        tick=20 - index,
                        salience=0.9 - (index * 0.05),
                        valence=0.1,
                    )
                    for index in range(6)
                ],
            )

    retrieval_service = StubRetrievalService()
    service = DialoguePreparationService(retrieval_service)

    result = service.prepare(_runtime_agent(), topic_text="winter grain planning")

    assert retrieval_service.calls == [("agent-1", "winter grain planning")]
    assert result.summary == "Ari keeps careful records of village life."
    assert result.goals == ["goal-0", "goal-1", "goal-2"]
    assert result.relationships == ["agent-2", "agent-3", "agent-4"]
    assert result.memories == ["memory-0", "memory-1", "memory-2", "memory-3", "memory-4"]
    assert "topic=winter grain planning" in result.prompt
    assert "goals=goal-0,goal-1,goal-2" in result.prompt
    assert "relationships=agent-2,agent-3,agent-4" in result.prompt


def test_dialogue_preparation_uses_general_topic_fallback_for_blank_queries() -> None:
    """Blank dialogue topics should still produce a valid compact prompt."""

    class StubRetrievalService:
        def retrieve_context(self, agent: AgentState, *, query_text: str) -> RetrievalContextResult:
            return RetrievalContextResult(
                summary="Ari is calm.",
                goals=[],
                relationships=[],
                memories=[],
            )

    result = DialoguePreparationService(StubRetrievalService()).prepare(_runtime_agent(), topic_text="   ")

    assert result.topic_text == "   "
    assert result.goals == []
    assert result.relationships == []
    assert result.memories == []
    assert "topic=general" in result.prompt
    assert "memories=none" in result.prompt
