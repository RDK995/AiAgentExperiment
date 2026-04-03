"""Deterministic utility scoring for fast-loop candidate actions."""

from __future__ import annotations

from app.agents.actions import ActionCandidate, ActionType
from app.agents.perception import PerceptionResult
from app.engine.world_state import AgentState


class UtilityAI:
    """Score candidate actions from current needs, obligations, and local perception."""

    def score_actions(self, agent: AgentState, context: PerceptionResult) -> list[ActionCandidate]:
        """Produce a deterministic set of ranked action candidates."""

        scores = {
            ActionType.DRINK: self.score_drink(agent, context),
            ActionType.EAT: self.score_eat(agent, context),
            ActionType.REST: self.score_rest(agent, context),
            ActionType.GATHER_FOOD: self.score_gather_food(agent, context),
            ActionType.FETCH_WATER: self.score_fetch_water(agent, context),
            ActionType.COOK: self.score_cook(agent, context),
            ActionType.SOCIALIZE: self.score_socialize(agent, context),
            ActionType.COURT: self.score_court(agent, context),
            ActionType.CARE_FOR_CHILD: self.score_care_for_child(agent, context),
            ActionType.WORK_FIELD: self.score_work_field(agent, context),
            ActionType.FLEE: self.score_flee(agent, context),
            ActionType.WANDER: self.score_wander(agent, context),
            ActionType.IDLE: 1.0,
        }
        candidates = [ActionCandidate(action_type=action, score=round(score, 3)) for action, score in scores.items()]
        return sorted(candidates, key=lambda item: (-item.score, item.action_type.value))

    @staticmethod
    def select_best_action(agent: AgentState, context: PerceptionResult) -> ActionCandidate:
        """Convenience helper returning the highest-ranked action."""

        return UtilityAI().score_actions(agent, context)[0]

    def score_drink(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.thirst * 1.8 + (0.5 if perception.nearby_water else -0.4) + self._hint_score(agent, "drink_soon")

    def score_eat(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hunger * 1.6 + (0.4 if perception.nearby_food else -0.3) + self._hint_score(agent, "eat_soon")

    def score_rest(self, agent: AgentState, perception: PerceptionResult) -> float:
        bed_bonus = 0.8 if perception.nearby_bed else 0.0
        return agent.fatigue * 1.4 + bed_bonus + self._hint_score(agent, "rest_soon")

    def score_gather_food(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hunger * 0.9 + (6.0 if perception.nearby_food else 1.5)

    def score_fetch_water(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.thirst * 0.95 + (6.0 if perception.nearby_water else 1.5)

    def score_cook(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hunger * 0.45 + (3.0 if "food" in perception.visible_items else 0.8)

    def score_socialize(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.loneliness * 1.1 + len(perception.visible_agents) * 2.0

    def score_court(self, agent: AgentState, perception: PerceptionResult) -> float:
        partner_bonus = 8.0 if perception.visible_partner else -1.0
        return max(0.0, agent.hope * 0.15 + agent.loneliness * 0.3 + partner_bonus)

    def score_care_for_child(self, agent: AgentState, perception: PerceptionResult) -> float:
        duty_bonus = 18.0 if agent.has_infant_care_duty else 0.0
        return duty_bonus + len(perception.nearby_infant_ids) * 12.0

    def score_work_field(self, agent: AgentState, perception: PerceptionResult) -> float:
        daylight_bonus = 4.0 if 6 <= perception.sim_hour < 18 else -3.0
        penalty = (agent.hunger + agent.thirst + agent.fatigue) * 0.15
        return daylight_bonus + max(0.0, 8.0 - penalty)

    def score_wander(self, agent: AgentState, perception: PerceptionResult) -> float:
        curiosity_bonus = 10.0 if "reflect_on_failures" in agent.pending_planner_hints else 0.0
        return 15.0 + curiosity_bonus

    @staticmethod
    def score_flee(agent: AgentState, perception: PerceptionResult) -> float:
        if perception.nearby_threat:
            return 250.0 + max(0.0, 100.0 - agent.safety)
        return max(0.0, 40.0 - agent.safety) * 0.2

    @staticmethod
    def _hint_score(agent: AgentState, hint: str) -> float:
        return 12.0 if hint in agent.pending_planner_hints else 0.0
