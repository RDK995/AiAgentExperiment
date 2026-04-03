"""Dialogue preparation helpers built on the shared retrieval pipeline."""

from __future__ import annotations

from app.engine.world_state import AgentState
from app.memory.retrieval import RetrievalContextService
from app.schemas.memory import DialogueContextResult


class DialoguePreparationService:
    """Prepare a compact speaking context from the authoritative retrieval pipeline."""

    def __init__(self, retrieval_service: RetrievalContextService) -> None:
        self._retrieval_service = retrieval_service

    def prepare(self, agent: AgentState, *, topic_text: str) -> DialogueContextResult:
        """Build dialogue-ready context from the same retrieval path used for reflection."""

        retrieved = self._retrieval_service.retrieve_context(agent, query_text=topic_text)
        goals = [goal.title for goal in retrieved.goals[:3]]
        relationships = [relationship.related_agent_id for relationship in retrieved.relationships[:3]]
        memories = [memory.raw_text for memory in retrieved.memories[:5]]
        prompt = self._build_prompt(
            agent_id=agent.agent_id,
            topic_text=topic_text,
            summary=retrieved.summary,
            goals=goals,
            relationships=relationships,
            memories=memories,
        )
        return DialogueContextResult(
            agent_id=agent.agent_id,
            topic_text=topic_text,
            summary=retrieved.summary,
            goals=goals,
            relationships=relationships,
            memories=memories,
            prompt=prompt,
        )

    @staticmethod
    def _build_prompt(
        *,
        agent_id: str,
        topic_text: str,
        summary: str,
        goals: list[str],
        relationships: list[str],
        memories: list[str],
    ) -> str:
        """Render a compact deterministic prompt stub for future dialogue systems."""

        topic = topic_text.strip() or "general"
        goal_text = ",".join(goals) if goals else "none"
        relationship_text = ",".join(relationships) if relationships else "none"
        memory_text = "; ".join(memories) if memories else "none"
        return (
            f"Speaker {agent_id}; topic={topic}; summary={summary}; "
            f"goals={goal_text}; relationships={relationship_text}; memories={memory_text}"
        )
