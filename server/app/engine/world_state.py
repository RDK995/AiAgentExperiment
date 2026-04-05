"""Authoritative world state models and bootstrap helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from app.db.enums import AgentSex, StageOfLife
from app.schemas.agent import AgentNeedState, AgentSnapshot, AgentStateSnapshot, MoodSchema, NeedsSchema
from app.schemas.api import SimulationSnapshot, TileSnapshot
from app.schemas.reflection import MemoryCandidate


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
class ItemStackState:
    """Simple world item stack visible to perception and task execution."""

    item_type: str
    x: int
    y: int
    quantity: int = 1


@dataclass(slots=True)
class ResourceNodeState:
    """Simple resource node visible to perception and utility scoring."""

    resource_type: str
    x: int
    y: int
    quantity: int = 1
    threat_level: float = 0.0


@dataclass(slots=True)
class AgentState:
    """Authoritative agent state stored by the simulation."""

    agent_id: str
    name: str
    x: int
    y: int
    sex: AgentSex = AgentSex.INTERSEX
    hunger: float = 0.0
    thirst: float = 0.0
    fatigue: float = 0.0
    warmth: float = 100.0
    health: float = 100.0
    stress: float = 0.0
    loneliness: float = 0.0
    safety: float = 100.0
    hope: float = 50.0
    grief: float = 0.0
    morale: float = 50.0
    shame: float = 0.0
    stage_of_life: StageOfLife = StageOfLife.ADULT
    age_ticks: int = 2_000
    alive: bool = True
    household_id: str | None = None
    partner_id: str | None = None
    parent_ids: list[str] = field(default_factory=list)
    current_action: str = "idle"
    current_goal: str = "Maintain daily routine"
    mood: str = "steady"
    plan_failure_count: int = 0
    slow_loop_trigger_flags: set[str] = field(default_factory=set)
    pending_planner_hints: list[str] = field(default_factory=list)
    family_orientation: float = 0.5
    bond_rejection_until_tick: int | None = None
    beliefs: list[str] = field(default_factory=list)
    memories: list[str] = field(default_factory=list)
    daily_summary_day_index: int | None = None
    daily_summary_candidates: list[MemoryCandidate] = field(default_factory=list)
    is_threat: bool = False
    has_infant_care_duty: bool = False
    household_planning_pressure: float = 0.0
    pregnancy_progress_ticks: int | None = None
    pregnancy_partner_id: str | None = None
    current_task_payload: dict[str, Any] | None = None
    task_queue: list[dict[str, Any]] = field(default_factory=list)

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

    def to_state_snapshot(self) -> AgentStateSnapshot:
        """Convert authoritative state into the richer backend inspection schema."""

        return AgentStateSnapshot(
            agent_id=self.agent_id,
            name=self.name,
            stage_of_life=self.stage_of_life,
            tile_x=self.x,
            tile_y=self.y,
            current_action=self.current_action,
            current_goal=self.current_goal,
            needs=NeedsSchema(
                hunger=self.hunger,
                thirst=self.thirst,
                fatigue=self.fatigue,
                warmth=self.warmth,
                health=self.health,
                stress=self.stress,
                loneliness=self.loneliness,
                safety=self.safety,
            ),
            mood=MoodSchema(
                hope=self.hope,
                grief=self.grief,
                morale=self.morale,
                shame=self.shame,
            ),
            household_id=self.household_id,
            partner_id=self.partner_id,
        )


@dataclass(slots=True)
class WorldState:
    """Root authoritative simulation state for the current world."""

    width: int
    height: int
    tick: int = 0
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    current_time: datetime = field(default_factory=lambda: datetime(2000, 1, 1, 6, 0, tzinfo=timezone.utc))
    day_index: int = 0
    weather: str = "clear"
    resource_level: float = 100.0
    crop_growth: float = 0.0
    tiles: list[TileState] = field(default_factory=list)
    agents: list[AgentState] = field(default_factory=list)
    items: list[ItemStackState] = field(default_factory=list)
    resources: list[ResourceNodeState] = field(default_factory=list)

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

    def update_weather(self, now: datetime) -> None:
        """Deterministically derive a prototype weather state from simulation time."""

        cycle = (now.hour + now.day) % 3
        self.weather = ["clear", "cloudy", "rain"][cycle]

    def update_resources(self, now: datetime) -> None:
        """Update prototype world resource levels."""

        delta = 1.0 if 6 <= now.hour < 18 else -0.5
        self.resource_level = max(0.0, min(200.0, self.resource_level + delta))

    def update_crops(self, now: datetime) -> None:
        """Update prototype crop growth."""

        growth_delta = 2.0 if self.weather == "rain" else 1.0
        self.crop_growth = min(100.0, self.crop_growth + growth_delta)

    def terrain_at(self, x: int, y: int) -> str:
        """Return terrain at a tile coordinate."""

        for tile in self.tiles:
            if tile.x == x and tile.y == y:
                return tile.terrain.value
        return TerrainType.GRASS.value

    def agent_by_id(self, agent_id: str) -> AgentState | None:
        """Look up an agent by id."""

        for agent in self.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def next_agent_id(self) -> str:
        """Generate the next deterministic agent identifier."""

        return f"agent-{len(self.agents) + 1}"


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

    return WorldState(
        width=width,
        height=height,
        day_index=datetime(2000, 1, 1, tzinfo=timezone.utc).toordinal(),
        tiles=tiles,
        agents=agents,
    )
