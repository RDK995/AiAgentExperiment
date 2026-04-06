"""Rule-based planning and interruption decisions for the fast loop."""

from __future__ import annotations

from app.agents.actions import ActionCandidate, ActionType, PlannedTask, SelectedAction, TaskType
from app.agents.planner_hints import enrich_tasks_with_hints, rerank_candidates_with_hints
from app.agents.perception import PerceptionResult
from app.engine.world_state import AgentState


class ActionPlanner:
    """Selects the highest-value objective and expands it into executable tasks."""

    def choose_action(
        self,
        agent: AgentState,
        candidates: list[ActionCandidate],
        perception: PerceptionResult | None = None,
    ) -> SelectedAction:
        """Choose the highest-value action with a simple continue/interrupt policy."""

        ranked_candidates = rerank_candidates_with_hints(agent, candidates, perception)
        top_candidate = ranked_candidates[0]
        tasks = self.plan_objective(top_candidate.action_type.value, agent, perception)
        if agent.current_action == top_candidate.action_type.value:
            return SelectedAction(
                action_type=top_candidate.action_type,
                interrupted_previous_action=False,
                tasks=tasks,
            )

        interrupted = agent.current_action not in {"idle", top_candidate.action_type.value}
        return SelectedAction(
            action_type=top_candidate.action_type,
            interrupted_previous_action=interrupted,
            tasks=tasks,
        )

    def plan_objective(
        self,
        objective: str,
        agent: AgentState,
        perception: PerceptionResult | None = None,
    ) -> list[PlannedTask]:
        """Expand a selected objective into a simple ordered task chain."""

        if objective == "drink":
            return enrich_tasks_with_hints(
                self._move_then(agent, perception, "water", [TaskType.FETCH_WATER, TaskType.DRINK], fallback=[TaskType.DRINK]),
                objective=objective,
                agent=agent,
            )
        if objective == "eat":
            if any(item in agent.inventory for item in ("meal", "food", "berries", "fruit", "fish")):
                return enrich_tasks_with_hints([PlannedTask(TaskType.EAT)], objective=objective, agent=agent)
            return enrich_tasks_with_hints(
                self._move_then(
                    agent,
                    perception,
                    "food",
                    [TaskType.GATHER_FOOD, TaskType.EAT],
                    fallback=[TaskType.EAT],
                ),
                objective=objective,
                agent=agent,
            )
        if objective == "sleep":
            return enrich_tasks_with_hints([PlannedTask(TaskType.SLEEP)], objective=objective, agent=agent)
        if objective == "rest":
            return enrich_tasks_with_hints([PlannedTask(TaskType.REST)], objective=objective, agent=agent)
        if objective == "move_to":
            return enrich_tasks_with_hints([PlannedTask(TaskType.MOVE_TO)], objective=objective, agent=agent)
        if objective == "fetch_water":
            return enrich_tasks_with_hints(
                self._move_then(
                    agent,
                    perception,
                    "water",
                    [TaskType.FETCH_WATER, TaskType.DRINK],
                    fallback=[TaskType.FETCH_WATER, TaskType.DRINK],
                ),
                objective=objective,
                agent=agent,
            )
        if objective == "gather_berries":
            return enrich_tasks_with_hints(
                self._move_then(
                    agent,
                    perception,
                    "food",
                    [TaskType.GATHER_BERRIES],
                    fallback=[TaskType.GATHER_BERRIES],
                ),
                objective=objective,
                agent=agent,
            )
        if objective == "fish":
            return enrich_tasks_with_hints(
                self._move_then(
                    agent,
                    perception,
                    "water",
                    [TaskType.FISH],
                    fallback=[TaskType.FISH],
                ),
                objective=objective,
                agent=agent,
            )
        if objective == "gather_food":
            if perception is not None and "berries" in perception.visible_resources:
                return enrich_tasks_with_hints(
                    self._move_then(
                        agent,
                        perception,
                        "food",
                        [TaskType.GATHER_BERRIES, TaskType.EAT],
                        fallback=[TaskType.GATHER_BERRIES, TaskType.EAT],
                    ),
                    objective=objective,
                    agent=agent,
                )
            if perception is not None and perception.nearby_water:
                return enrich_tasks_with_hints(
                    self._move_then(
                        agent,
                        perception,
                        "water",
                        [TaskType.FISH, TaskType.EAT],
                        fallback=[TaskType.FISH, TaskType.EAT],
                    ),
                    objective=objective,
                    agent=agent,
                )
            return enrich_tasks_with_hints(
                self._move_then(
                    agent,
                    perception,
                    "food",
                    [TaskType.GATHER_FOOD, TaskType.EAT],
                    fallback=[TaskType.GATHER_FOOD, TaskType.EAT],
                ),
                objective=objective,
                agent=agent,
            )
        if objective == "plant_crop":
            return enrich_tasks_with_hints([PlannedTask(TaskType.PLANT_CROP)], objective=objective, agent=agent)
        if objective == "harvest_crop":
            return enrich_tasks_with_hints([PlannedTask(TaskType.HARVEST_CROP)], objective=objective, agent=agent)
        if objective == "chop_wood":
            return enrich_tasks_with_hints([PlannedTask(TaskType.CHOP_WOOD)], objective=objective, agent=agent)
        if objective in {"cook", "cook_food"}:
            return enrich_tasks_with_hints([PlannedTask(TaskType.COOK_FOOD)], objective=objective, agent=agent)
        if objective == "store_item":
            return enrich_tasks_with_hints([PlannedTask(TaskType.STORE_ITEM)], objective=objective, agent=agent)
        if objective == "retrieve_item":
            return enrich_tasks_with_hints([PlannedTask(TaskType.RETRIEVE_ITEM)], objective=objective, agent=agent)
        if objective == "feed_household":
            return enrich_tasks_with_hints([
                PlannedTask(TaskType.MOVE_TO, metadata={"label": "storage"}),
                PlannedTask(TaskType.INSPECT_STOCK),
                PlannedTask(TaskType.RETRIEVE_ITEM, metadata={"item_type": "food"}),
                PlannedTask(TaskType.MOVE_TO, metadata={"label": "home"}),
                PlannedTask(TaskType.COOK_FOOD),
                PlannedTask(TaskType.SHARE_FOOD_HOME),
            ], objective=objective, agent=agent)
        if objective == "greet":
            return enrich_tasks_with_hints([PlannedTask(TaskType.GREET, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "talk":
            return enrich_tasks_with_hints([PlannedTask(TaskType.TALK, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "give_item":
            metadata = _social_target_metadata(agent, perception)
            metadata.setdefault("item_type", "food")
            return enrich_tasks_with_hints([PlannedTask(TaskType.GIVE_ITEM, metadata=metadata)], objective=objective, agent=agent)
        if objective == "ask_help":
            return enrich_tasks_with_hints([PlannedTask(TaskType.ASK_HELP, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "insult":
            return enrich_tasks_with_hints([PlannedTask(TaskType.INSULT, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "apologize":
            return enrich_tasks_with_hints([PlannedTask(TaskType.APOLOGIZE, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "socialize":
            target_metadata = _social_target_metadata(agent, perception)
            return enrich_tasks_with_hints(
                [PlannedTask(TaskType.GREET, metadata=dict(target_metadata)), PlannedTask(TaskType.TALK, metadata=target_metadata)],
                objective=objective,
                agent=agent,
            )
        if objective == "court":
            return enrich_tasks_with_hints([PlannedTask(TaskType.COURT, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "propose_bond":
            return enrich_tasks_with_hints([PlannedTask(TaskType.PROPOSE_BOND, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "comfort":
            return enrich_tasks_with_hints([PlannedTask(TaskType.COMFORT, metadata=_social_target_metadata(agent, perception))], objective=objective, agent=agent)
        if objective == "mourn":
            return enrich_tasks_with_hints([PlannedTask(TaskType.MOURN)], objective=objective, agent=agent)
        if objective == "care_for_infant":
            tasks = self._move_then(
                    agent,
                    perception,
                    "infant",
                    [TaskType.CARE_FOR_INFANT],
                    fallback=[PlannedTask(TaskType.CARE_FOR_INFANT, metadata=_infant_target_metadata(perception))],
                )
            _apply_target_metadata(tasks, _infant_target_metadata(perception))
            return enrich_tasks_with_hints(tasks, objective=objective, agent=agent)
        if objective == "care_for_child":
            if perception is not None and perception.nearby_infant_ids:
                tasks = self._move_then(
                        agent,
                        perception,
                        "infant",
                        [TaskType.CARE_FOR_INFANT],
                        fallback=[PlannedTask(TaskType.CARE_FOR_INFANT, metadata=_infant_target_metadata(perception))],
                    )
                _apply_target_metadata(tasks, _infant_target_metadata(perception))
                return enrich_tasks_with_hints(tasks, objective=objective, agent=agent)
            tasks = self._move_then(
                    agent,
                    perception,
                    "infant",
                    [TaskType.CARE_FOR_CHILD],
                    fallback=[TaskType.CARE_FOR_CHILD],
                )
            _apply_target_metadata(tasks, _infant_target_metadata(perception))
            return enrich_tasks_with_hints(tasks, objective=objective, agent=agent)
        if objective == "escort_child":
            return enrich_tasks_with_hints([PlannedTask(TaskType.ESCORT_CHILD, metadata=_infant_target_metadata(perception))], objective=objective, agent=agent)
        if objective == "teach_skill":
            metadata = _infant_target_metadata(perception)
            metadata.setdefault("skill_name", "foraging")
            return enrich_tasks_with_hints([PlannedTask(TaskType.TEACH_SKILL, metadata=metadata)], objective=objective, agent=agent)
        if objective == "share_food_home":
            return enrich_tasks_with_hints([PlannedTask(TaskType.SHARE_FOOD_HOME)], objective=objective, agent=agent)
        if objective == "work_field":
            return enrich_tasks_with_hints([PlannedTask(TaskType.WORK_FIELD)], objective=objective, agent=agent)
        if objective == "wander":
            return enrich_tasks_with_hints([PlannedTask(TaskType.WANDER_STEP)], objective=objective, agent=agent)
        if objective == "flee":
            return enrich_tasks_with_hints([PlannedTask(TaskType.FLEE_STEP)], objective=objective, agent=agent)
        return enrich_tasks_with_hints([PlannedTask(TaskType.WANDER_STEP)], objective=objective, agent=agent)

    @staticmethod
    def _move_then(
        agent: AgentState,
        perception: PerceptionResult | None,
        target_kind: str,
        terminal_tasks: list[TaskType],
        fallback: list[TaskType | PlannedTask],
    ) -> list[PlannedTask]:
        """Prepend a move task when compact perception includes a useful target."""

        if perception is None:
            return [task if isinstance(task, PlannedTask) else PlannedTask(task) for task in fallback]

        target_x, target_y = _target_coords(perception, target_kind)
        if target_x is None or target_y is None:
            return [task if isinstance(task, PlannedTask) else PlannedTask(task) for task in fallback]

        tasks: list[PlannedTask] = []
        if (agent.x, agent.y) != (target_x, target_y):
            tasks.append(
                PlannedTask(
                    TaskType.MOVE_TO,
                    target_x=target_x,
                    target_y=target_y,
                    metadata={"label": target_kind},
                )
            )
        tasks.extend(PlannedTask(task_type) for task_type in terminal_tasks)
        return tasks


def _target_coords(perception: PerceptionResult, target_kind: str) -> tuple[int | None, int | None]:
    """Read compact target coordinates from perception."""

    if target_kind == "water":
        return (perception.nearest_water_x, perception.nearest_water_y)
    if target_kind == "food":
        return (perception.nearest_food_x, perception.nearest_food_y)
    if target_kind == "infant":
        return (perception.nearest_infant_x, perception.nearest_infant_y)
    return (None, None)


def _social_target_metadata(agent: AgentState, perception: PerceptionResult | None) -> dict[str, str]:
    """Resolve a deterministic social target for planner tasks when one is visible."""

    if perception is None:
        return {}
    if agent.partner_id is not None and agent.partner_id in perception.visible_agents:
        return {"target_agent_id": agent.partner_id}
    if perception.visible_agents:
        return {"target_agent_id": sorted(perception.visible_agents)[0]}
    return {}


def _infant_target_metadata(perception: PerceptionResult | None) -> dict[str, str]:
    """Resolve a deterministic infant/child target for family tasks."""

    if perception is None or not perception.nearby_infant_ids:
        return {}
    return {"target_agent_id": sorted(perception.nearby_infant_ids)[0]}


def _apply_target_metadata(tasks: list[PlannedTask], metadata: dict[str, str]) -> None:
    """Attach resolved target metadata to the terminal interaction task when available."""

    if not metadata or not tasks:
        return
    tasks[-1].metadata.update(metadata)
