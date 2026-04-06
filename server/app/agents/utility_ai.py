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
            ActionType.SLEEP: self.score_sleep(agent, context),
            ActionType.DRINK: self.score_drink(agent, context),
            ActionType.EAT: self.score_eat(agent, context),
            ActionType.REST: self.score_rest(agent, context),
            ActionType.GATHER_BERRIES: self.score_gather_berries(agent, context),
            ActionType.FISH: self.score_fish(agent, context),
            ActionType.GATHER_FOOD: self.score_gather_food(agent, context),
            ActionType.FETCH_WATER: self.score_fetch_water(agent, context),
            ActionType.PLANT_CROP: self.score_plant_crop(agent, context),
            ActionType.HARVEST_CROP: self.score_harvest_crop(agent, context),
            ActionType.CHOP_WOOD: self.score_chop_wood(agent, context),
            ActionType.COOK_FOOD: self.score_cook(agent, context),
            ActionType.COOK: self.score_cook(agent, context),
            ActionType.STORE_ITEM: self.score_store_item(agent, context),
            ActionType.RETRIEVE_ITEM: self.score_retrieve_item(agent, context),
            ActionType.GREET: self.score_greet(agent, context),
            ActionType.TALK: self.score_talk(agent, context),
            ActionType.GIVE_ITEM: self.score_give_item(agent, context),
            ActionType.ASK_HELP: self.score_ask_help(agent, context),
            ActionType.INSULT: self.score_insult(agent, context),
            ActionType.APOLOGIZE: self.score_apologize(agent, context),
            ActionType.SOCIALIZE: self.score_socialize(agent, context),
            ActionType.COURT: self.score_court(agent, context),
            ActionType.PROPOSE_BOND: self.score_propose_bond(agent, context),
            ActionType.COMFORT: self.score_comfort(agent, context),
            ActionType.MOURN: self.score_mourn(agent, context),
            ActionType.CARE_FOR_INFANT: self.score_care_for_child(agent, context),
            ActionType.CARE_FOR_CHILD: self.score_care_for_child(agent, context),
            ActionType.ESCORT_CHILD: self.score_escort_child(agent, context),
            ActionType.TEACH_SKILL: self.score_teach_skill(agent, context),
            ActionType.SHARE_FOOD_HOME: self.score_share_food_home(agent, context),
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
        return (
            agent.thirst * 1.8
            + (0.5 if perception.nearby_water else -0.4)
            + self._hint_score(agent, "drink_soon")
            + self._hint_score(agent, "focus_on_recovery", weight=7.0)
        )

    def score_sleep(self, agent: AgentState, perception: PerceptionResult) -> float:
        bed_bonus = 2.0 if perception.nearby_bed else -0.5
        night_bonus = 3.0 if perception.sim_hour >= 21 or perception.sim_hour <= 5 else 0.0
        return agent.fatigue * 1.15 + bed_bonus + night_bonus

    def score_eat(self, agent: AgentState, perception: PerceptionResult) -> float:
        return (
            agent.hunger * 1.6
            + (0.4 if perception.nearby_food else -0.3)
            + self._hint_score(agent, "eat_soon")
            + self._hint_score(agent, "focus_on_recovery", weight=5.0)
            + self._hint_score(agent, "prioritize_food_security", weight=9.0)
        )

    def score_rest(self, agent: AgentState, perception: PerceptionResult) -> float:
        bed_bonus = 0.8 if perception.nearby_bed else 0.0
        return (
            agent.fatigue * 1.4
            + bed_bonus
            + self._hint_score(agent, "rest_soon")
            + self._hint_score(agent, "focus_on_recovery", weight=12.0)
        )

    def score_gather_berries(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hunger * 0.8 + (7.0 if "berries" in perception.visible_resources else 0.5)

    def score_fish(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hunger * 0.7 + (6.0 if perception.nearby_water else 0.0)

    def score_gather_food(self, agent: AgentState, perception: PerceptionResult) -> float:
        return (
            agent.hunger * 0.9
            + (6.0 if perception.nearby_food else 1.5)
            + self._hint_score(agent, "prioritize_food_security", weight=11.0)
            + self._hint_score(agent, "gather_resources", weight=8.0)
        )

    def score_fetch_water(self, agent: AgentState, perception: PerceptionResult) -> float:
        return (
            agent.thirst * 0.95
            + (6.0 if perception.nearby_water else 1.5)
            + self._hint_score(agent, "focus_on_recovery", weight=4.0)
            + self._hint_score(agent, "gather_resources", weight=6.0)
        )

    def score_plant_crop(self, agent: AgentState, perception: PerceptionResult) -> float:
        return max(0.0, 8.0 - (agent.hunger + agent.thirst + agent.fatigue) * 0.08) + (2.0 if 6 <= perception.sim_hour < 18 else -2.0)

    def score_harvest_crop(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hunger * 0.65 + (2.0 if 6 <= perception.sim_hour < 18 else -1.0)

    def score_chop_wood(self, agent: AgentState, perception: PerceptionResult) -> float:
        return max(0.0, 7.0 - (agent.hunger + agent.thirst + agent.fatigue) * 0.08) + (1.0 if perception.terrain == "forest" else 0.0)

    def score_cook(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hunger * 0.45 + (3.0 if "food" in perception.visible_items else 0.8)

    @staticmethod
    def score_store_item(agent: AgentState, perception: PerceptionResult) -> float:
        return 5.0 if agent.inventory else 0.0

    @staticmethod
    def score_retrieve_item(agent: AgentState, perception: PerceptionResult) -> float:
        return 6.0 if agent.home_inventory and (agent.hunger > 40.0 or agent.thirst > 40.0) else 0.0

    def score_greet(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.loneliness * 0.15 + len(perception.visible_agents) * 1.5

    def score_talk(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.loneliness * 0.45 + len(perception.visible_agents) * 1.8

    @staticmethod
    def score_give_item(agent: AgentState, perception: PerceptionResult) -> float:
        return 4.0 if agent.inventory and perception.visible_agents else 0.0

    def score_ask_help(self, agent: AgentState, perception: PerceptionResult) -> float:
        return max(agent.stress, 100.0 - agent.safety) * 0.08 + (3.0 if perception.visible_agents else 0.0)

    def score_insult(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.stress * 0.06 + len(perception.visible_agents) * 0.5

    def score_apologize(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.shame * 0.4 + len(perception.visible_agents) * 0.5

    def score_socialize(self, agent: AgentState, perception: PerceptionResult) -> float:
        partner_hint = self._hint_score(agent, "visit_partner", weight=9.0)
        return agent.loneliness * 1.1 + len(perception.visible_agents) * 2.0 + partner_hint

    def score_court(self, agent: AgentState, perception: PerceptionResult) -> float:
        partner_bonus = 8.0 if perception.visible_partner else -1.0
        return max(
            0.0,
            agent.hope * 0.15
            + agent.loneliness * 0.3
            + partner_bonus
            + self._hint_score(agent, "visit_partner", weight=12.0),
        )

    def score_propose_bond(self, agent: AgentState, perception: PerceptionResult) -> float:
        partner_bonus = 6.0 if perception.visible_partner else 0.0
        return max(0.0, agent.hope * 0.12 + agent.loneliness * 0.1 + partner_bonus)

    def score_comfort(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.grief * 0.15 + agent.stress * 0.08 + len(perception.visible_agents) * 1.0

    def score_mourn(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.grief * 0.5

    def score_care_for_child(self, agent: AgentState, perception: PerceptionResult) -> float:
        duty_bonus = 18.0 if agent.has_infant_care_duty else 0.0
        return duty_bonus + len(perception.nearby_infant_ids) * 12.0

    def score_escort_child(self, agent: AgentState, perception: PerceptionResult) -> float:
        return (12.0 if agent.has_infant_care_duty else 0.0) + len(perception.visible_agents) * 0.5

    def score_teach_skill(self, agent: AgentState, perception: PerceptionResult) -> float:
        return agent.hope * 0.08 + len(perception.visible_agents) * 0.8

    @staticmethod
    def score_share_food_home(agent: AgentState, perception: PerceptionResult) -> float:
        has_food = any(item in agent.inventory for item in ("meal", "food", "berries", "fish"))
        return 7.0 if has_food and agent.household_id is not None else 0.0

    def score_work_field(self, agent: AgentState, perception: PerceptionResult) -> float:
        daylight_bonus = 4.0 if 6 <= perception.sim_hour < 18 else -3.0
        penalty = (agent.hunger + agent.thirst + agent.fatigue) * 0.15
        return (
            daylight_bonus
            + max(0.0, 8.0 - penalty)
            + self._hint_score(agent, "gather_resources", weight=9.0)
            + self._hint_score(agent, "prioritize_food_security", weight=4.0)
        )

    def score_wander(self, agent: AgentState, perception: PerceptionResult) -> float:
        curiosity_bonus = 10.0 if "reflect_on_failures" in agent.pending_planner_hints else 0.0
        return 15.0 + curiosity_bonus

    @staticmethod
    def score_flee(agent: AgentState, perception: PerceptionResult) -> float:
        if perception.nearby_threat:
            return 250.0 + max(0.0, 100.0 - agent.safety)
        return max(0.0, 40.0 - agent.safety) * 0.2

    @staticmethod
    def _hint_score(agent: AgentState, hint: str, *, weight: float = 12.0) -> float:
        return weight if hint in agent.pending_planner_hints else 0.0
