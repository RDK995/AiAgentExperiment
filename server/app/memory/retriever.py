"""Prototype memory retriever for slow-loop context collection."""

from __future__ import annotations

from app.engine.world_state import AgentState


class MemoryRetriever:
    """Retrieve recent memory/event strings from agent state."""

    def retrieve_recent_events(self, agent: AgentState) -> list[str]:
        """Return a bounded list of recent memories."""

        queued_candidates = [
            candidate.text
            for candidate in sorted(
                agent.daily_summary_candidates,
                key=lambda candidate: (-candidate.salience, candidate.text),
            )
        ]
        recent_memories = list(reversed(agent.memories[-10:]))
        combined = queued_candidates + recent_memories
        deduplicated: list[str] = []
        seen: set[str] = set()
        for entry in combined:
            if entry in seen:
                continue
            deduplicated.append(entry)
            seen.add(entry)
            if len(deduplicated) >= 5:
                break
        return deduplicated
