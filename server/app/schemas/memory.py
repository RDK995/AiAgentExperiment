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


class RetrievedGoalRecord(BaseModel):
    """Compact goal summary returned by the retrieval pipeline."""

    model_config = ConfigDict(extra="forbid")

    title: str
    priority: float = Field(ge=0.0)
    status: str


class RetrievedRelationshipRecord(BaseModel):
    """Compact relationship summary returned by the retrieval pipeline."""

    model_config = ConfigDict(extra="forbid")

    related_agent_id: str
    score: float
    trust: float = Field(ge=0.0, le=1.0)
    admiration: float = Field(ge=0.0, le=1.0)
    familiarity: float = Field(ge=0.0, le=1.0)
    attraction: float = Field(ge=0.0, le=1.0)
    obligation: float = Field(ge=0.0, le=1.0)
    resentment: float = Field(ge=0.0, le=1.0)
    fear: float = Field(ge=0.0, le=1.0)
    dependency: float = Field(ge=0.0, le=1.0)
    last_interaction_tick: int | None = Field(default=None, ge=0)


class RetrievedMemoryRecord(BaseModel):
    """Compact episodic memory summary returned by the retrieval pipeline."""

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    raw_text: str
    tick: int | None = Field(default=None, ge=0)
    salience: float = Field(ge=0.0, le=1.0)
    valence: float = Field(ge=-1.0, le=1.0)
    location_x: int | None = None
    location_y: int | None = None
    participant_ids: list[str] = Field(default_factory=list)
    similarity_score: float | None = None
    rerank_score: float | None = None


class RetrievalContextResult(BaseModel):
    """Assembled reflection/dialogue retrieval context."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    goals: list[RetrievedGoalRecord] = Field(default_factory=list)
    relationships: list[RetrievedRelationshipRecord] = Field(default_factory=list)
    memories: list[RetrievedMemoryRecord] = Field(default_factory=list)


class DialogueContextResult(BaseModel):
    """Compact dialogue-facing context assembled from the retrieval pipeline."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    topic_text: str
    summary: str
    goals: list[str] = Field(default_factory=list)
    relationships: list[str] = Field(default_factory=list)
    memories: list[str] = Field(default_factory=list)
    prompt: str
