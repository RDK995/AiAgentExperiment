"""Pydantic schemas for agent transport contracts."""

from pydantic import BaseModel, Field


class GridPosition(BaseModel):
    """2D tile position in authoritative world coordinates."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)


class AgentNeedState(BaseModel):
    """Snapshot of the agent's current needs."""

    hunger: float = Field(ge=0.0, le=100.0)
    thirst: float = Field(ge=0.0, le=100.0)
    fatigue: float = Field(ge=0.0, le=100.0)


class AgentSnapshot(BaseModel):
    """Serialized view of an agent sent to clients."""

    agent_id: str
    name: str
    position: GridPosition
    needs: AgentNeedState
    current_action: str
