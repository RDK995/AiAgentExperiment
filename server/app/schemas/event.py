"""Pydantic models for simulation events."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.memory import WorldEventRecord


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


class WorldEventSchema(BaseModel):
    """Client/API-safe DTO for a persisted or serialized world event."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    tick: int = Field(ge=0)
    event_type: str
    actor_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    location_x: int | None = None
    location_y: int | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_record(cls, record: WorldEventRecord) -> "WorldEventSchema":
        """Build a transport DTO from the persisted world-event record schema."""

        return cls(
            event_id=str(record.id),
            tick=record.tick,
            event_type=record.event_type,
            actor_ids=[str(actor_id) for actor_id in record.actor_ids],
            target_ids=[str(target_id) for target_id in record.target_ids],
            location_x=record.location_x,
            location_y=record.location_y,
            payload=record.payload,
        )
