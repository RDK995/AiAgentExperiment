"""Rule-based planning and interruption decisions for the fast loop."""

from __future__ import annotations

from app.agents.actions import ActionCandidate, ActionType, PlannedTask, SelectedAction, TaskType
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

        top_candidate = candidates[0]
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
            return self._move_then(agent, perception, "water", [TaskType.FETCH_WATER, TaskType.DRINK], fallback=[TaskType.DRINK])
        if objective == "eat":
            return self._move_then(
                agent,
                perception,
                "food",
                [TaskType.GATHER_FOOD, TaskType.EAT],
                fallback=[TaskType.EAT],
            )
        if objective in {"sleep", "rest"}:
            return [PlannedTask(TaskType.REST)]
        if objective == "fetch_water":
            return self._move_then(
                agent,
                perception,
                "water",
                [TaskType.FETCH_WATER, TaskType.DRINK],
                fallback=[TaskType.FETCH_WATER, TaskType.DRINK],
            )
        if objective == "gather_food":
            return self._move_then(
                agent,
                perception,
                "food",
                [TaskType.GATHER_FOOD, TaskType.EAT],
                fallback=[TaskType.GATHER_FOOD, TaskType.EAT],
            )
        if objective == "feed_household":
            return [
                PlannedTask(TaskType.MOVE_TO, metadata={"label": "storage"}),
                PlannedTask(TaskType.INSPECT_STOCK),
                PlannedTask(TaskType.GATHER_FOOD),
                PlannedTask(TaskType.MOVE_TO, metadata={"label": "home"}),
                PlannedTask(TaskType.COOK),
                PlannedTask(TaskType.DISTRIBUTE_FOOD),
            ]
        if objective == "socialize":
            return [PlannedTask(TaskType.SOCIALIZE)]
        if objective == "court":
            return [PlannedTask(TaskType.COURT)]
        if objective == "care_for_child":
            return self._move_then(
                agent,
                perception,
                "infant",
                [TaskType.CARE_FOR_CHILD],
                fallback=[TaskType.CARE_FOR_CHILD],
            )
        if objective == "work_field":
            return [PlannedTask(TaskType.WORK_FIELD)]
        if objective == "wander":
            return [PlannedTask(TaskType.WANDER_STEP)]
        if objective == "flee":
            return [PlannedTask(TaskType.FLEE_STEP)]
        return [PlannedTask(TaskType.WANDER_STEP)]

    @staticmethod
    def _move_then(
        agent: AgentState,
        perception: PerceptionResult | None,
        target_kind: str,
        terminal_tasks: list[TaskType],
        fallback: list[TaskType],
    ) -> list[PlannedTask]:
        """Prepend a move task when compact perception includes a useful target."""

        if perception is None:
            return [PlannedTask(task_type) for task_type in fallback]

        target_x, target_y = _target_coords(perception, target_kind)
        if target_x is None or target_y is None:
            return [PlannedTask(task_type) for task_type in fallback]

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
