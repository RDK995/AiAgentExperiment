"""Pydantic transport models for persisted memory records."""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class EpisodicMemoryRecord(BaseModel):
    """Serialized episodic memory row for backend integration and debugging."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: UUID
    tick: int = Field(ge=0)
    event_type: str
    location_x: int | None = None
    location_y: int | None = None
    raw_text: str
    valence: float
    salience: float
    participant_ids: list[UUID] = Field(default_factory=list)
    decay_rate: float = Field(ge=0.0)
    archived: bool = False


class SemanticBeliefRecord(BaseModel):
    """Serialized semantic belief row for backend integration and debugging."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    agent_id: UUID
    subject_type: str
    subject_id: UUID | None = None
    predicate: str
    object_value: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence_count: int = Field(ge=1)
    last_supported_tick: int = Field(ge=0)


class WorldEventRecord(BaseModel):
    """Serialized world event row for telemetry/debug integration."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    tick: int = Field(ge=0)
    event_type: str
    actor_ids: list[UUID] = Field(default_factory=list)
    target_ids: list[UUID] = Field(default_factory=list)
    location_x: int | None = None
    location_y: int | None = None
    payload: dict[str, object] = Field(default_factory=dict)
