"""Structured reflection workflow schemas."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import GoalType


class ReflectionContext(BaseModel):
    """Inputs to the slow-loop reflection workflow."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    trigger_reasons: list[str] = Field(default_factory=list)
    autobiography: str
    recent_events: list[str] = Field(default_factory=list)


class ReflectionResult(BaseModel):
    """Validated reflection outputs to be applied to agent state."""

    model_config = ConfigDict(extra="forbid")

    goals: list[str] = Field(default_factory=list)
    beliefs: list[str] = Field(default_factory=list)
    memory_entries: list[str] = Field(default_factory=list)
    planner_hints: list[str] = Field(default_factory=list)


class BeliefUpdate(BaseModel):
    """Structured belief change proposed by a reflection workflow."""

    model_config = ConfigDict(extra="forbid")

    subject_type: str
    subject_id: str | None = None
    predicate: str
    object_value: str
    confidence_delta: float = Field(ge=-1.0, le=1.0)


class GoalUpdate(BaseModel):
    """Structured goal mutation proposed by reflection."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    action: Literal["create", "reprioritize", "complete", "abandon"]
    goal_type: GoalType
    title: str
    priority: float = Field(ge=0.0)
    horizon_days: int = Field(ge=0)


class MemoryCandidate(BaseModel):
    """Candidate memory synthesized by reflection before persistence."""

    model_config = ConfigDict(extra="forbid")

    text: str
    salience: float = Field(ge=0.0, le=1.0)
    valence: float = Field(ge=-1.0, le=1.0)


class ReflectionOutput(BaseModel):
    """Structured reflection output contract for future model-backed cognition."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    mood_delta: dict[str, float] = Field(default_factory=dict)
    belief_updates: list[BeliefUpdate] = Field(default_factory=list)
    goal_updates: list[GoalUpdate] = Field(default_factory=list)
    memory_candidates: list[MemoryCandidate] = Field(default_factory=list)
    tomorrow_intentions: list[str] = Field(default_factory=list)

    def to_reflection_result(self) -> ReflectionResult:
        """Adapt richer structured reflection output into the current legacy contract."""

        beliefs = []
        for update in self.belief_updates:
            if update.subject_id is None:
                beliefs.append(f"{update.subject_type}:{update.predicate}:{update.object_value}")
            else:
                beliefs.append(
                    f"{update.subject_type}:{update.subject_id}:{update.predicate}:{update.object_value}"
                )

        return ReflectionResult(
            goals=[goal.title for goal in self.goal_updates],
            beliefs=beliefs,
            memory_entries=[memory.text for memory in self.memory_candidates],
            planner_hints=list(self.tomorrow_intentions),
        )
