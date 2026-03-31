"""Structured reflection workflow schemas."""

from __future__ import annotations

from pydantic import BaseModel, Field


class ReflectionContext(BaseModel):
    """Inputs to the slow-loop reflection workflow."""

    agent_id: str
    trigger_reasons: list[str] = Field(default_factory=list)
    autobiography: str
    recent_events: list[str] = Field(default_factory=list)


class ReflectionResult(BaseModel):
    """Validated reflection outputs to be applied to agent state."""

    goals: list[str] = Field(default_factory=list)
    beliefs: list[str] = Field(default_factory=list)
    memory_entries: list[str] = Field(default_factory=list)
    planner_hints: list[str] = Field(default_factory=list)
