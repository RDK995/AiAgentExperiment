"""Pydantic schemas for agent transport contracts."""

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import StageOfLife


class GridPosition(BaseModel):
    """2D tile position in authoritative world coordinates."""

    model_config = ConfigDict(extra="forbid")

    x: int = Field(ge=0)
    y: int = Field(ge=0)


class AgentNeedState(BaseModel):
    """Snapshot of the agent's current needs."""

    model_config = ConfigDict(extra="forbid")

    hunger: float = Field(ge=0.0, le=100.0)
    thirst: float = Field(ge=0.0, le=100.0)
    fatigue: float = Field(ge=0.0, le=100.0)


class NeedsSchema(BaseModel):
    """Detailed need state for richer backend-facing snapshot contracts."""

    model_config = ConfigDict(extra="forbid")

    hunger: float = Field(ge=0.0, le=100.0)
    thirst: float = Field(ge=0.0, le=100.0)
    fatigue: float = Field(ge=0.0, le=100.0)
    warmth: float = Field(ge=0.0, le=100.0)
    health: float = Field(ge=0.0, le=100.0)
    stress: float = Field(ge=0.0, le=100.0)
    loneliness: float = Field(ge=0.0, le=100.0)
    safety: float = Field(ge=0.0, le=100.0)


class MoodSchema(BaseModel):
    """Serialized mood state for richer backend-facing agent snapshots."""

    model_config = ConfigDict(extra="forbid")

    hope: float = Field(ge=0.0, le=100.0)
    grief: float = Field(ge=0.0, le=100.0)
    morale: float = Field(ge=0.0, le=100.0)
    shame: float = Field(ge=0.0, le=100.0)


class AgentSnapshot(BaseModel):
    """Serialized view of an agent sent to clients."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    agent_id: str
    name: str
    position: GridPosition
    needs: AgentNeedState
    current_action: str
    stage_of_life: StageOfLife | None = None
    household_id: str | None = None
    partner_id: str | None = None
    current_goal: str | None = None


class AgentStateSnapshot(BaseModel):
    """Richer backend snapshot contract for agent state inspection."""

    model_config = ConfigDict(extra="forbid", use_enum_values=True)

    agent_id: str
    name: str
    stage_of_life: StageOfLife
    tile_x: int = Field(ge=0)
    tile_y: int = Field(ge=0)
    current_action: str | None = None
    current_goal: str | None = None
    needs: NeedsSchema
    mood: MoodSchema
    household_id: str | None = None
    partner_id: str | None = None
