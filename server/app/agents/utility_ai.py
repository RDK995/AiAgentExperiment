"""Deterministic utility scoring for fast-loop candidate actions."""

from __future__ import annotations

from app.agents.actions import ActionCandidate, ActionType
from app.agents.perception import PerceivedContext
from app.engine.world_state import AgentState


class UtilityAI:
    """Score candidate actions from current needs and planner hints."""

    def score_actions(self, agent: AgentState, context: PerceivedContext) -> list[ActionCandidate]:
        """Produce a deterministic set of ranked action candidates."""

        hint_bonus = 10.0 if "reflect_on_failures" in agent.pending_planner_hints else 0.0

        candidates = [
            ActionCandidate(ActionType.EAT, context.hunger + self._hint_score(agent, "eat_soon")),
            ActionCandidate(ActionType.DRINK, context.thirst + self._hint_score(agent, "drink_soon")),
            ActionCandidate(ActionType.REST, context.fatigue + self._hint_score(agent, "rest_soon")),
            ActionCandidate(ActionType.WANDER, 15.0 + hint_bonus),
            ActionCandidate(ActionType.IDLE, 5.0),
        ]
        return sorted(candidates, key=lambda item: item.score, reverse=True)

    @staticmethod
    def _hint_score(agent: AgentState, hint: str) -> float:
        return 12.0 if hint in agent.pending_planner_hints else 0.0
