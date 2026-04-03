"""Action model helpers for the agent fast loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """Supported prototype action kinds."""

    EAT = "eat"
    DRINK = "drink"
    REST = "rest"
    GATHER_FOOD = "gather_food"
    FETCH_WATER = "fetch_water"
    COOK = "cook"
    SOCIALIZE = "socialize"
    COURT = "court"
    CARE_FOR_CHILD = "care_for_child"
    WORK_FIELD = "work_field"
    FLEE = "flee"
    WANDER = "wander"
    IDLE = "idle"


class TaskType(str, Enum):
    """Executable task kinds emitted by the planner."""

    MOVE_TO = "move_to"
    DRINK = "drink"
    EAT = "eat"
    REST = "rest"
    GATHER_FOOD = "gather_food"
    FETCH_WATER = "fetch_water"
    COOK = "cook"
    SOCIALIZE = "socialize"
    COURT = "court"
    CARE_FOR_CHILD = "care_for_child"
    WORK_FIELD = "work_field"
    WANDER_STEP = "wander_step"
    FLEE_STEP = "flee_step"
    INSPECT_STOCK = "inspect_stock"
    DISTRIBUTE_FOOD = "distribute_food"


@dataclass(slots=True)
class ActionCandidate:
    """Scored action candidate."""

    action_type: ActionType
    score: float


@dataclass(slots=True)
class PlannedTask:
    """A single executable task emitted by the rule-based planner."""

    task_type: TaskType
    target_x: int | None = None
    target_y: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        """Serialize the task for storage on authoritative agent state."""

        return {
            "task_type": self.task_type.value,
            "target_x": self.target_x,
            "target_y": self.target_y,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "PlannedTask":
        """Hydrate a task from authoritative agent state."""

        return cls(
            task_type=TaskType(payload["task_type"]),
            target_x=payload.get("target_x"),
            target_y=payload.get("target_y"),
            metadata=dict(payload.get("metadata", {})),
        )


@dataclass(slots=True)
class SelectedAction:
    """Chosen action for execution."""

    action_type: ActionType
    interrupted_previous_action: bool = False
    tasks: list[PlannedTask] = field(default_factory=list)
