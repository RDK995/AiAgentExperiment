"""Shared API transport models for snapshots and endpoint contracts."""

from datetime import datetime
from typing import Annotated, Any

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import AgentSnapshot, AgentStateSnapshot
from app.schemas.event import WorldEventSchema

NonEmptyShortText = Annotated[str, Field(min_length=1, max_length=120, pattern=r".*\S.*")]
NonEmptyQueryText = Annotated[str, Field(min_length=1, max_length=240, pattern=r".*\S.*")]


class TileSnapshot(BaseModel):
    """Serialized tile information used by the client renderer."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    terrain: str
    walkable: bool = True


class WorldSnapshot(BaseModel):
    """Serialized world grid snapshot."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    tiles: list[TileSnapshot]


class SimulationSnapshot(BaseModel):
    """Top-level snapshot emitted by the authoritative simulation backend."""

    model_config = ConfigDict(extra="forbid")

    tick: int = Field(ge=0)
    world: WorldSnapshot
    agents: list[AgentSnapshot]
    generated_at: datetime


class RunSimulationRequest(BaseModel):
    """Request payload for advancing the simulation by multiple ticks."""

    model_config = ConfigDict(extra="forbid")

    ticks: int = Field(default=1, ge=1, le=100)


class WorldSeedRequest(BaseModel):
    """Optional request payload for reseeding the prototype world."""

    model_config = ConfigDict(extra="forbid")

    agent_count: int | None = Field(default=None, ge=1, le=200)


class MoveAgentRequest(BaseModel):
    """Request payload for a client-submitted movement attempt."""

    model_config = ConfigDict(extra="forbid")

    agent_id: NonEmptyShortText
    target_x: int = Field(ge=0)
    target_y: int = Field(ge=0)


class ErrorResponse(BaseModel):
    """Consistent error payload used across route groups."""

    model_config = ConfigDict(extra="forbid")

    error: str
    message: str


class ChunkResponse(BaseModel):
    """Minimal chunk view backed by the authoritative world grid."""

    model_config = ConfigDict(extra="forbid")

    anchor_x: int = Field(ge=0)
    anchor_y: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    tiles: list[TileSnapshot]
    agents: list[AgentStateSnapshot]


class SeedResponse(BaseModel):
    """Summary returned after reseeding the prototype world."""

    model_config = ConfigDict(extra="forbid")

    status: str
    tick: int = Field(ge=0)
    width: int = Field(ge=1)
    height: int = Field(ge=1)
    seeded_agents: int = Field(ge=0)


class GoalSummary(BaseModel):
    """Simple transport-safe goal summary for an agent."""

    model_config = ConfigDict(extra="forbid")

    title: str
    status: str


class AgentListResponse(BaseModel):
    """Consistent response wrapper for agent listings."""

    model_config = ConfigDict(extra="forbid")

    agents: list[AgentStateSnapshot]


class RelationshipSummary(BaseModel):
    """Simple relationship summary for debugging and agent inspection."""

    model_config = ConfigDict(extra="forbid")

    related_agent_id: str
    kind: str
    score: float = Field(ge=0.0)


class RelationshipsResponse(BaseModel):
    """Consistent response wrapper for agent relationships."""

    model_config = ConfigDict(extra="forbid")

    relationships: list[RelationshipSummary]


class GoalsResponse(BaseModel):
    """Consistent response wrapper for agent goals."""

    model_config = ConfigDict(extra="forbid")

    goals: list[GoalSummary]


class TimelineEntry(BaseModel):
    """Merged timeline entry drawn from events and memories."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    summary: str
    tick: int | None = Field(default=None, ge=0)


class TimelineResponse(BaseModel):
    """Consistent response wrapper for merged timeline entries."""

    model_config = ConfigDict(extra="forbid")

    entries: list[TimelineEntry]


class MemoryEpisodeSummary(BaseModel):
    """Lightweight episodic memory summary."""

    model_config = ConfigDict(extra="forbid")

    text: str
    tick: int | None = Field(default=None, ge=0)


class EpisodesResponse(BaseModel):
    """Consistent response wrapper for episodic memories."""

    model_config = ConfigDict(extra="forbid")

    episodes: list[MemoryEpisodeSummary]


class DailySummaryCandidateSummary(BaseModel):
    """Transport-safe daily-summary candidate view for one agent."""

    model_config = ConfigDict(extra="forbid")

    text: str
    salience: float = Field(ge=0.0, le=1.0)
    valence: float = Field(ge=-1.0, le=1.0)


class DailySummaryCandidatesResponse(BaseModel):
    """Consistent response wrapper for queued daily-summary candidates."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    day_index: int | None = Field(default=None, ge=0)
    candidates: list[DailySummaryCandidateSummary]


class BeliefSummary(BaseModel):
    """Lightweight semantic belief summary."""

    model_config = ConfigDict(extra="forbid")

    text: str


class BeliefsResponse(BaseModel):
    """Consistent response wrapper for semantic beliefs."""

    model_config = ConfigDict(extra="forbid")

    beliefs: list[BeliefSummary]


class MemoryRetrieveRequest(BaseModel):
    """Request payload for simple memory retrieval."""

    model_config = ConfigDict(extra="forbid")

    query: NonEmptyQueryText
    limit: int = Field(default=5, ge=1, le=20)


class MemoryRetrieveResponse(BaseModel):
    """Memory retrieval response payload."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    query: str
    matches: list[str]


class MemorySummarizeResponse(BaseModel):
    """Simple memory summary response."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    summary: str
    memory_count: int = Field(ge=0)


class DebugMetricsResponse(BaseModel):
    """High-level debug metrics for the current runtime."""

    model_config = ConfigDict(extra="forbid")

    tick: int = Field(ge=0)
    sim_time: str
    total_recorded_ticks: int = Field(ge=0)
    pending_scheduler_tasks: list[str]
    last_tick_event_count: int = Field(ge=0)
    last_tick_event_types: list[str]
    last_tick_event_type_counts: dict[str, int]


class ReplayEventResponse(BaseModel):
    """Replay/debug view of recent authoritative events."""

    model_config = ConfigDict(extra="forbid")

    event_id: str
    tick: int = Field(ge=0)
    event_type: str
    agent_id: str | None = None
    sim_time: str
    payload: dict[str, Any]


class ReplayResponse(BaseModel):
    """Consistent response wrapper for replay/debug event lists."""

    model_config = ConfigDict(extra="forbid")

    events: list[ReplayEventResponse]


class AgentInspectResponse(BaseModel):
    """Detailed debug inspection payload for one agent."""

    model_config = ConfigDict(extra="forbid")

    agent: AgentStateSnapshot
    beliefs: list[str]
    memories: list[str]
    pending_planner_hints: list[str]
    trigger_flags: list[str]


class HouseholdInspectResponse(BaseModel):
    """Minimal household inspection payload."""

    model_config = ConfigDict(extra="forbid")

    household_id: str
    agents: list[AgentStateSnapshot]


class SpawnAgentRequest(BaseModel):
    """Admin request for spawning a prototype agent."""

    model_config = ConfigDict(extra="forbid")

    name: NonEmptyShortText | None = None
    tile_x: int | None = Field(default=None, ge=0)
    tile_y: int | None = Field(default=None, ge=0)


class SpawnAgentResponse(BaseModel):
    """Admin response after spawning a prototype agent."""

    model_config = ConfigDict(extra="forbid")

    status: str
    agent: AgentStateSnapshot


class SpawnFoodRequest(BaseModel):
    """Admin request for increasing world food/resources."""

    model_config = ConfigDict(extra="forbid")

    tile_x: int = Field(ge=0)
    tile_y: int = Field(ge=0)
    quantity: int = Field(default=1, ge=1)
    item_type: NonEmptyShortText = "food"


class SpawnFoodResponse(BaseModel):
    """Admin response after adding prototype food/resources."""

    model_config = ConfigDict(extra="forbid")

    status: str
    item_type: str
    quantity: int = Field(ge=1)
    tile_x: int = Field(ge=0)
    tile_y: int = Field(ge=0)
    resource_level: float = Field(ge=0.0)


class AdvanceDaysResponse(BaseModel):
    """Admin response after advancing the simulation by coarse day units."""

    model_config = ConfigDict(extra="forbid")

    days_requested: int = Field(ge=1)
    ticks_run: int = Field(ge=1)
    final_tick: int = Field(ge=0)
    current_time: str


class ResetWorldResponse(BaseModel):
    """Admin response after resetting the prototype world."""

    model_config = ConfigDict(extra="forbid")

    status: str
    tick: int = Field(ge=0)
    agent_count: int = Field(ge=0)


class ForceReflectResponse(BaseModel):
    """Structured response for a forced reflection pass."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    applied: bool
    planner_hints: list[str]
    trigger_reasons: list[str]


class RecentWorldEventsResponse(BaseModel):
    """Response wrapper for recent world events."""

    model_config = ConfigDict(extra="forbid")

    events: list[WorldEventSchema]
