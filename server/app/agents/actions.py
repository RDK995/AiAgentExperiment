"""Action model helpers for the agent fast loop."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionType(str, Enum):
    """Supported prototype action kinds."""

    EAT = "eat"
    DRINK = "drink"
    REST = "rest"
    WANDER = "wander"
    IDLE = "idle"


@dataclass(slots=True)
class ActionCandidate:
    """Scored action candidate."""

    action_type: ActionType
    score: float


@dataclass(slots=True)
class SelectedAction:
    """Chosen action for execution."""

    action_type: ActionType
    interrupted_previous_action: bool = False
