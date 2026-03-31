"""Pydantic models for simulation events."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Event types emitted by the authoritative simulation."""

    ACTION_EXECUTED = "action_executed"
    PLAN_FAILED = "plan_failed"
    SOCIAL_MILESTONE = "social_milestone"
    MAJOR_LIFE_EVENT = "major_life_event"
    DAY_ROLLOVER = "day_rollover"
    TELEMETRY = "telemetry"
    SLOW_LOOP_COMPLETED = "slow_loop_completed"


class SimulationEvent(BaseModel):
    """Structured event emitted by world, agent, and telemetry systems."""

    type: EventType
    tick: int = Field(ge=0)
    sim_time: datetime
    agent_id: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)
