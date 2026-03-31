"""Prototype memory writer for validated slow-loop outputs."""

from __future__ import annotations

from app.engine.world_state import AgentState


class MemoryWriter:
    """Persist slow-loop memory summaries on the agent state."""

    def write(self, agent: AgentState, memory_entries: list[str]) -> None:
        """Append validated memory entries to the agent memory log."""

        agent.memories.extend(memory_entries)
        agent.memories = agent.memories[-20:]
