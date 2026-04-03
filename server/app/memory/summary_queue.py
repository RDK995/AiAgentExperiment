"""Daily-summary queue helpers for high-salience memory candidates."""

from __future__ import annotations

from app.engine.world_state import AgentState
from app.schemas.reflection import MemoryCandidate


class DailySummaryQueue:
    """Queue high-value memories for future daily reflection summarization."""

    def __init__(self, minimum_salience: float = 0.60) -> None:
        self._minimum_salience = minimum_salience

    def enqueue(self, agent: AgentState, *, day_index: int, candidate: MemoryCandidate) -> bool:
        """Queue one candidate if it is salient enough and not already queued for the day."""

        if candidate.salience < self._minimum_salience:
            return False
        if agent.daily_summary_day_index != day_index:
            agent.daily_summary_day_index = day_index
            agent.daily_summary_candidates = []
        if any(existing.text == candidate.text for existing in agent.daily_summary_candidates):
            return False
        agent.daily_summary_candidates.append(candidate)
        return True
