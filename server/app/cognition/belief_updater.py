"""Belief updater for validated slow-loop outputs."""

from __future__ import annotations

from app.engine.world_state import AgentState


class BeliefUpdater:
    """Applies validated belief updates to authoritative agent state."""

    def apply(self, agent: AgentState, beliefs: list[str]) -> None:
        """Replace beliefs with the current validated set."""

        agent.beliefs = list(beliefs)
