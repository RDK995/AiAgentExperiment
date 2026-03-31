"""Shared API transport models for snapshots."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.agent import AgentSnapshot


class TileSnapshot(BaseModel):
    """Serialized tile information used by the client renderer."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    terrain: str
    walkable: bool = True


class WorldSnapshot(BaseModel):
    """Serialized world grid snapshot."""

    width: int = Field(ge=1)
    height: int = Field(ge=1)
    tiles: list[TileSnapshot]


class SimulationSnapshot(BaseModel):
    """Top-level snapshot emitted by the authoritative simulation backend."""

    tick: int = Field(ge=0)
    world: WorldSnapshot
    agents: list[AgentSnapshot]
    generated_at: datetime


class RunSimulationRequest(BaseModel):
    """Request payload for advancing the simulation by multiple ticks."""

    ticks: int = Field(default=1, ge=1, le=100)


class MoveAgentRequest(BaseModel):
    """Request payload for a client-submitted movement attempt."""

    agent_id: str
    target_x: int = Field(ge=0)
    target_y: int = Field(ge=0)
