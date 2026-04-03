"""Pydantic models for simulation events."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.memory import WorldEventRecord


class EventType(str, Enum):
    """Event types emitted by the authoritative simulation."""

    AGENT_ATE = "agent_ate"
    AGENT_DRANK = "agent_drank"
    GIFT_GIVEN = "gift_given"
    INSULT_SPOKEN = "insult_spoken"
    PROPOSAL_MADE = "proposal_made"
    PROPOSAL_ACCEPTED = "proposal_accepted"
    PREGNANCY_STARTED = "pregnancy_started"
    CHILD_BORN = "child_born"
    AGENT_DIED = "agent_died"
    FOOD_STORE_EMPTY = "food_store_empty"
    CROP_FAILED = "crop_failed"
    ACTION_EXECUTED = "action_executed"
    PLAN_FAILED = "plan_failed"
    TASK_STARTED = "task_started"
    TASK_PROGRESS = "task_progress"
    TASK_COMPLETED = "task_completed"
    TASK_INTERRUPTED = "task_interrupted"
    SOCIAL_MILESTONE = "social_milestone"
    MAJOR_LIFE_EVENT = "major_life_event"
    BIRTH = "birth"
    DEATH = "death"
    DAY_ROLLOVER = "day_rollover"
    TELEMETRY = "telemetry"
    SLOW_LOOP_COMPLETED = "slow_loop_completed"


class SimulationEvent(BaseModel):
    """Structured event emitted by world, agent, and telemetry systems."""

    event_id: str | None = None
    type: EventType
    tick: int = Field(ge=0)
    sim_time: datetime
    agent_id: str | None = None
    actor_ids: list[str] = Field(default_factory=list)
    target_ids: list[str] = Field(default_factory=list)
    location_x: int | None = None
    location_y: int | None = None
    source_module: str | None = None
    payload: dict[str, object] = Field(default_factory=dict)

    def model_post_init(self, __context: object) -> None:
        """Backfill the richer actor contract from the legacy single-agent field."""

        if not self.actor_ids and self.agent_id is not None:
            self.actor_ids = [self.agent_id]


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
    source_module: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_simulation_event(
        cls,
        event: SimulationEvent,
        *,
        fallback_event_id: str | None = None,
    ) -> "WorldEventSchema":
        """Build a transport DTO directly from an authoritative simulation event."""

        return cls(
            event_id=event.event_id or fallback_event_id or f"{event.tick}-{event.type.value}",
            tick=event.tick,
            event_type=event.type.value,
            actor_ids=list(event.actor_ids),
            target_ids=list(event.target_ids),
            location_x=event.location_x,
            location_y=event.location_y,
            source_module=event.source_module,
            payload=dict(event.payload),
        )

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
            source_module=getattr(record, "source_module", None),
            payload=record.payload,
        )
