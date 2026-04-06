"""Shared API transport models for snapshots and endpoint contracts."""

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.agent import AgentSnapshot, AgentStateSnapshot
from app.schemas.event import WorldEventSchema
from app.schemas.metrics import DailyMetricsSnapshot

NonEmptyShortText = Annotated[str, Field(min_length=1, max_length=120, pattern=r".*\S.*")]
NonEmptyQueryText = Annotated[str, Field(min_length=1, max_length=240, pattern=r".*\S.*")]


class TileSnapshot(BaseModel):
    """Serialized tile information used by the client renderer."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    terrain: str
    walkable: bool = True


class SeedStructureSnapshot(BaseModel):
    """Static structure definition used by the presentation layer seed renderer."""

    model_config = ConfigDict(extra="forbid")

    structure_id: str
    structure_type: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(default=1, ge=1)
    height: int = Field(default=1, ge=1)
    label: str | None = None


class SeedMarkerSnapshot(BaseModel):
    """Static marker definition for world landmarks and debug labels."""

    model_config = ConfigDict(extra="forbid")

    marker_id: str
    marker_type: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    label: str | None = None


class WorldSnapshot(BaseModel):
    """Serialized world grid snapshot."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    tiles: list[TileSnapshot]


class SeedWorldSnapshot(BaseModel):
    """Expanded static world seed definition for client bootstrap and debugging."""

    model_config = ConfigDict(extra="forbid")

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    tiles: list[TileSnapshot]
    structures: list[SeedStructureSnapshot]
    markers: list[SeedMarkerSnapshot]


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
    seed_id: str | None = Field(default=None, min_length=1, max_length=120)


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
    seed_id: str | None = None


class SeedAgentSummary(BaseModel):
    """Static seed-facing agent definition used by the Godot bootstrap layer."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    agent_id: str
    name: str
    stage_of_life: str
    sex: str
    household_id: str | None = None
    home_structure_id: str | None = None
    partner_id: str | None = None
    position: dict[str, int]
    role: str | None = None


class SeedHouseholdSummary(BaseModel):
    """Static household grouping for dashboard/debug presentation."""

    model_config = ConfigDict(extra="forbid")

    household_id: str
    home_structure_id: str
    member_ids: list[str]
    label: str | None = None


class SeedSocialLinkSummary(BaseModel):
    """Static social structure link seeded into the v1 village scenario."""

    model_config = ConfigDict(extra="forbid")

    kind: str
    agent_ids: list[str]
    note: str | None = None


class WorldSeedDefinitionResponse(BaseModel):
    """Expanded deterministic seed definition used by the Godot client bootstrap."""

    model_config = ConfigDict(extra="forbid")

    seed_id: str
    world: SeedWorldSnapshot
    agents: list[SeedAgentSummary]
    households: list[SeedHouseholdSummary]
    social_links: list[SeedSocialLinkSummary]


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
    latest_daily_metrics: DailyMetricsSnapshot | None = None
    recent_daily_metrics: list[DailyMetricsSnapshot] = Field(default_factory=list)


class DailyMetricsDebugResponse(BaseModel):
    """Compact daily metrics debug response for dashboards and debug clients."""

    model_config = ConfigDict(extra="forbid")

    current: DailyMetricsSnapshot | None = None
    latest: DailyMetricsSnapshot | None = None
    recent: list[DailyMetricsSnapshot] = Field(default_factory=list)


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
    completed_stages: list[str] = Field(default_factory=list)
    failure_stage: str | None = None
    validation_errors: list[str] = Field(default_factory=list)


class ReflectionRunSummary(BaseModel):
    """Compact debug/audit view of one reflection workflow execution."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    trigger_reasons: list[str]
    applied: bool
    planner_hints: list[str]
    completed_stages: list[str] = Field(default_factory=list)
    failure_stage: str | None = None
    validation_errors: list[str] = Field(default_factory=list)


class ReflectionRunsResponse(BaseModel):
    """Response wrapper for recent reflection workflow executions."""

    model_config = ConfigDict(extra="forbid")

    reflections: list[ReflectionRunSummary]


class RecentWorldEventsResponse(BaseModel):
    """Response wrapper for recent world events."""

    model_config = ConfigDict(extra="forbid")

    events: list[WorldEventSchema]


class WorldStreamBatchResponse(BaseModel):
    """One live batch emitted to presentation clients."""

    model_config = ConfigDict(extra="forbid")

    snapshot: SimulationSnapshot
    events: list[WorldEventSchema]


class WorldStreamEnvelope(BaseModel):
    """Envelope emitted on the live world stream."""

    model_config = ConfigDict(extra="forbid")

    message_type: Literal["seed_definition", "snapshot_batch", "warning"]
    seed_definition: WorldSeedDefinitionResponse | None = None
    snapshot_batch: WorldStreamBatchResponse | None = None
    warning: str | None = None
