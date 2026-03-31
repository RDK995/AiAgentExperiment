"""Action continuation and interruption decisions for the fast loop."""

from __future__ import annotations

from app.agents.actions import ActionCandidate, SelectedAction
from app.engine.world_state import AgentState


class ActionPlanner:
    """Selects whether to continue or interrupt the current action."""

    def choose_action(self, agent: AgentState, candidates: list[ActionCandidate]) -> SelectedAction:
        """Choose the highest-value action with a simple continue/interrupt policy."""

        top_candidate = candidates[0]
        if agent.current_action == top_candidate.action_type.value:
            return SelectedAction(action_type=top_candidate.action_type, interrupted_previous_action=False)

        interrupted = agent.current_action != "idle"
        return SelectedAction(action_type=top_candidate.action_type, interrupted_previous_action=interrupted)
