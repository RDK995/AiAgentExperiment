"""Prototype memory retriever for slow-loop context collection."""

from __future__ import annotations

from app.engine.world_state import AgentState


class MemoryRetriever:
    """Retrieve recent memory/event strings from agent state."""

    def retrieve_recent_events(self, agent: AgentState) -> list[str]:
        """Return a bounded list of recent memories."""

        return list(agent.memories[-5:])
