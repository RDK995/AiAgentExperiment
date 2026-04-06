"""Action model helpers for the agent fast loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class ActionType(str, Enum):
    """Supported prototype action kinds."""

    MOVE_TO = "move_to"
    EAT = "eat"
    DRINK = "drink"
    SLEEP = "sleep"
    REST = "rest"
    GATHER_BERRIES = "gather_berries"
    FISH = "fish"
    GATHER_FOOD = "gather_food"
    FETCH_WATER = "fetch_water"
    PLANT_CROP = "plant_crop"
    HARVEST_CROP = "harvest_crop"
    CHOP_WOOD = "chop_wood"
    COOK_FOOD = "cook_food"
    COOK = "cook"
    STORE_ITEM = "store_item"
    RETRIEVE_ITEM = "retrieve_item"
    GREET = "greet"
    TALK = "talk"
    GIVE_ITEM = "give_item"
    ASK_HELP = "ask_help"
    INSULT = "insult"
    APOLOGIZE = "apologize"
    SOCIALIZE = "socialize"
    COURT = "court"
    PROPOSE_BOND = "propose_bond"
    COMFORT = "comfort"
    MOURN = "mourn"
    CARE_FOR_INFANT = "care_for_infant"
    CARE_FOR_CHILD = "care_for_child"
    ESCORT_CHILD = "escort_child"
    TEACH_SKILL = "teach_skill"
    SHARE_FOOD_HOME = "share_food_home"
    WORK_FIELD = "work_field"
    FLEE = "flee"
    WANDER = "wander"
    IDLE = "idle"


class TaskType(str, Enum):
    """Executable task kinds emitted by the planner."""

    MOVE_TO = "move_to"
    DRINK = "drink"
    EAT = "eat"
    SLEEP = "sleep"
    REST = "rest"
    GATHER_BERRIES = "gather_berries"
    FISH = "fish"
    GATHER_FOOD = "gather_food"
    FETCH_WATER = "fetch_water"
    PLANT_CROP = "plant_crop"
    HARVEST_CROP = "harvest_crop"
    CHOP_WOOD = "chop_wood"
    COOK_FOOD = "cook_food"
    COOK = "cook"
    STORE_ITEM = "store_item"
    RETRIEVE_ITEM = "retrieve_item"
    GREET = "greet"
    TALK = "talk"
    GIVE_ITEM = "give_item"
    ASK_HELP = "ask_help"
    INSULT = "insult"
    APOLOGIZE = "apologize"
    SOCIALIZE = "socialize"
    COURT = "court"
    PROPOSE_BOND = "propose_bond"
    COMFORT = "comfort"
    MOURN = "mourn"
    CARE_FOR_INFANT = "care_for_infant"
    CARE_FOR_CHILD = "care_for_child"
    ESCORT_CHILD = "escort_child"
    TEACH_SKILL = "teach_skill"
    SHARE_FOOD_HOME = "share_food_home"
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
