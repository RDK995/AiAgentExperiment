"""Authoritative world state models and bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum

from app.schemas.agent import AgentNeedState, AgentSnapshot
from app.schemas.api import SimulationSnapshot, TileSnapshot


class TerrainType(str, Enum):
    """Supported terrain types for the initial tile grid."""

    GRASS = "grass"
    PATH = "path"
    WATER = "water"


@dataclass(slots=True)
class TileState:
    """Authoritative terrain tile state."""

    x: int
    y: int
    terrain: TerrainType
    walkable: bool = True


@dataclass(slots=True)
class AgentState:
    """Authoritative agent state stored by the simulation."""

    agent_id: str
    name: str
    x: int
    y: int
    hunger: float = 0.0
    thirst: float = 0.0
    fatigue: float = 0.0
    current_action: str = "idle"

    def advance_needs(self) -> None:
        """Apply deterministic need growth for a single simulation tick."""

        self.hunger = min(100.0, self.hunger + 1.5)
        self.thirst = min(100.0, self.thirst + 2.0)
        self.fatigue = min(100.0, self.fatigue + 0.75)

    def to_snapshot(self) -> AgentSnapshot:
        """Convert authoritative state into the public API schema."""

        return AgentSnapshot(
            agent_id=self.agent_id,
            name=self.name,
            position={"x": self.x, "y": self.y},
            needs=AgentNeedState(
                hunger=self.hunger,
                thirst=self.thirst,
                fatigue=self.fatigue,
            ),
            current_action=self.current_action,
        )


@dataclass(slots=True)
class WorldState:
    """Root authoritative simulation state for the current world."""

    width: int
    height: int
    tick: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    tiles: list[TileState] = field(default_factory=list)
    agents: list[AgentState] = field(default_factory=list)

    def to_snapshot(self) -> SimulationSnapshot:
        """Serialize the world into a transport-safe snapshot contract."""

        return SimulationSnapshot(
            tick=self.tick,
            world={
                "width": self.width,
                "height": self.height,
                "tiles": [
                    TileSnapshot(
                        x=tile.x,
                        y=tile.y,
                        terrain=tile.terrain,
                        walkable=tile.walkable,
                    )
                    for tile in self.tiles
                ],
            },
            agents=[agent.to_snapshot() for agent in self.agents],
            generated_at=datetime.now(timezone.utc),
        )


def build_initial_world_state(width: int, height: int, initial_agent_count: int) -> WorldState:
    """Create a simple deterministic starter world for the first vertical slice."""

    tiles: list[TileState] = []
    center_y = height // 2

    for y in range(height):
        for x in range(width):
            terrain = TerrainType.PATH if y == center_y else TerrainType.GRASS
            walkable = terrain is not TerrainType.WATER
            tiles.append(TileState(x=x, y=y, terrain=terrain, walkable=walkable))

    agents: list[AgentState] = []
    for index in range(initial_agent_count):
        agents.append(
            AgentState(
                agent_id=f"agent-{index + 1}",
                name=f"Villager {index + 1}",
                x=min(width - 1, 2 + index * 2),
                y=center_y,
            )
        )

    return WorldState(width=width, height=height, tiles=tiles, agents=agents)
