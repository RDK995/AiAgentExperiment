"""Shared persistence enums for authoritative simulation records."""

from __future__ import annotations

from enum import Enum


class AgentSex(str, Enum):
    FEMALE = "female"
    MALE = "male"
    INTERSEX = "intersex"


class FacingDirection(str, Enum):
    NORTH = "north"
    EAST = "east"
    SOUTH = "south"
    WEST = "west"


class StageOfLife(str, Enum):
    INFANT = "infant"
    CHILD = "child"
    ADOLESCENT = "adolescent"
    ADULT = "adult"
    ELDER = "elder"


class KinshipType(str, Enum):
    NONE = "none"
    PARENT = "parent"
    CHILD = "child"
    SIBLING = "sibling"
    COUSIN = "cousin"


class PairBondState(str, Enum):
    COURTING = "courting"
    BONDED = "bonded"
    SEPARATED = "separated"


class PregnancyStatus(str, Enum):
    ACTIVE = "active"
    ENDED = "ended"
    MISCARRIAGE = "miscarriage"
    BIRTH = "birth"


class GoalType(str, Enum):
    FAMILY = "family"
    STATUS = "status"
    SAFETY = "safety"
    WEALTH = "wealth"
    EXPLORATION = "exploration"


class GoalStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    ABANDONED = "abandoned"


class GoalSource(str, Enum):
    SEEDED = "seeded"
    REFLECTION = "reflection"
    INHERITED = "inherited"


class InventoryOwnerType(str, Enum):
    AGENT = "agent"
    BUILDING = "building"
    GROUND = "ground"
