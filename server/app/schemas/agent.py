"""Pydantic schemas for agent transport contracts."""

from pydantic import BaseModel, ConfigDict, Field


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


class AgentSnapshot(BaseModel):
    """Serialized view of an agent sent to clients."""

    model_config = ConfigDict(extra="forbid")

    agent_id: str
    name: str
    position: GridPosition
    needs: AgentNeedState
    current_action: str
