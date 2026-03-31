"""Goal updater for validated slow-loop outputs."""

from __future__ import annotations

from app.engine.world_state import AgentState


class GoalUpdater:
    """Applies validated goal updates to authoritative agent state."""

    def apply(self, agent: AgentState, goals: list[str]) -> None:
        """Set the current goal from the first validated goal."""

        if goals:
            agent.current_goal = goals[0]
