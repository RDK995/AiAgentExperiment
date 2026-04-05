"""Deterministic world-seed loading for backend bootstrap and Godot presentation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.db.enums import AgentSex, StageOfLife
from app.engine.world_state import AgentState, ResourceNodeState, TerrainType, TileState, WorldState
from app.schemas.api import (
    SeedAgentSummary,
    SeedHouseholdSummary,
    SeedMarkerSnapshot,
    SeedSocialLinkSummary,
    SeedStructureSnapshot,
    SeedWorldSnapshot,
    TileSnapshot,
    WorldSeedDefinitionResponse,
)


class WorldSeedService:
    """Load and expand deterministic village seeds shared by backend and Godot."""

    _seed_dir = Path(__file__).resolve().parents[3] / "client-godot" / "data" / "world_seeds"

    def load_seed_definition(self, seed_id: str = "v1_village") -> WorldSeedDefinitionResponse:
        """Return an expanded seed definition for presentation/debug consumers."""

        raw = self._load_raw_seed(seed_id)
        width = int(raw["world"]["width"])
        height = int(raw["world"]["height"])
        tiles = self._expand_tiles(raw["world"])

        return WorldSeedDefinitionResponse(
            seed_id=seed_id,
            world=SeedWorldSnapshot(
                width=width,
                height=height,
                tiles=tiles,
                structures=[
                    SeedStructureSnapshot(**structure)
                    for structure in raw["world"].get("structures", [])
                ],
                markers=[
                    SeedMarkerSnapshot(**marker)
                    for marker in raw["world"].get("markers", [])
                ],
            ),
            agents=[
                SeedAgentSummary(
                    agent_id=str(agent["agent_id"]),
                    name=str(agent["name"]),
                    stage_of_life=str(agent["stage_of_life"]),
                    sex=str(agent["sex"]),
                    household_id=agent.get("household_id"),
                    home_structure_id=agent.get("home_structure_id"),
                    partner_id=agent.get("partner_id"),
                    position={
                        "x": int(agent["position"]["x"]),
                        "y": int(agent["position"]["y"]),
                    },
                    role=agent.get("role"),
                )
                for agent in raw.get("agents", [])
            ],
            households=[
                SeedHouseholdSummary(
                    household_id=str(household["household_id"]),
                    home_structure_id=str(household["home_structure_id"]),
                    member_ids=[str(member_id) for member_id in household.get("member_ids", [])],
                    label=household.get("label"),
                )
                for household in raw.get("households", [])
            ],
            social_links=[
                SeedSocialLinkSummary(
                    kind=str(link["kind"]),
                    agent_ids=[str(agent_id) for agent_id in link.get("agent_ids", [])],
                    note=link.get("note"),
                )
                for link in raw.get("social_links", [])
            ],
        )

    def build_world_state(self, seed_id: str = "v1_village") -> WorldState:
        """Build authoritative runtime state from one deterministic seed definition."""

        definition = self.load_seed_definition(seed_id)
        world = WorldState(
            width=definition.world.width,
            height=definition.world.height,
            day_index=0,
            tiles=[
                TileState(
                    x=tile.x,
                    y=tile.y,
                    terrain=TerrainType(tile.terrain),
                    walkable=tile.walkable,
                )
                for tile in definition.world.tiles
            ],
            agents=[
                AgentState(
                    agent_id=agent.agent_id,
                    name=agent.name,
                    x=int(agent.position["x"]),
                    y=int(agent.position["y"]),
                    sex=AgentSex(agent.sex),
                    stage_of_life=StageOfLife(agent.stage_of_life),
                    age_ticks=_age_ticks_for_stage(agent.stage_of_life),
                    household_id=agent.household_id,
                    partner_id=agent.partner_id,
                    current_goal=_default_goal_for_stage(agent.stage_of_life),
                )
                for agent in definition.agents
            ],
            resources=[
                ResourceNodeState(resource_type="berries", x=5, y=32, quantity=24),
            ],
        )
        world.day_index = world.current_time.toordinal()
        self._apply_seed_roles(world, definition)
        return world

    def _load_raw_seed(self, seed_id: str) -> dict[str, Any]:
        if Path(seed_id).name != seed_id:
            raise ValueError(f"Unknown world seed '{seed_id}'.")
        path = self._seed_dir / f"{seed_id}.json"
        if not path.exists():
            path = self._seed_dir / f"{seed_id}_seed.json"
        if not path.exists():
            raise ValueError(f"Unknown world seed '{seed_id}'.")
        return json.loads(path.read_text(encoding="utf-8"))

    def _expand_tiles(self, world_definition: dict[str, Any]) -> list[TileSnapshot]:
        width = int(world_definition["width"])
        height = int(world_definition["height"])
        default_terrain = str(world_definition.get("default_terrain", TerrainType.GRASS.value))
        terrain_grid = [
            [default_terrain for _ in range(width)]
            for _ in range(height)
        ]

        for region in world_definition.get("terrain_regions", []):
            terrain = str(region["terrain"])
            start_x = int(region["x"])
            start_y = int(region["y"])
            region_width = int(region["width"])
            region_height = int(region["height"])
            for y in range(start_y, min(height, start_y + region_height)):
                for x in range(start_x, min(width, start_x + region_width)):
                    terrain_grid[y][x] = terrain

        tiles: list[TileSnapshot] = []
        for y in range(height):
            for x in range(width):
                terrain = terrain_grid[y][x]
                tiles.append(
                    TileSnapshot(
                        x=x,
                        y=y,
                        terrain=terrain,
                        walkable=terrain != TerrainType.WATER.value,
                    )
                )
        return tiles

    def _apply_seed_roles(self, world: WorldState, definition: WorldSeedDefinitionResponse) -> None:
        agent_index = {agent.agent_id: agent for agent in world.agents}

        for link in definition.social_links:
            if link.kind == "rival_pair" and len(link.agent_ids) == 2:
                first = agent_index.get(link.agent_ids[0])
                second = agent_index.get(link.agent_ids[1])
                if first is not None and second is not None:
                    first.beliefs.append(f"seed:rival:{second.agent_id}")
                    second.beliefs.append(f"seed:rival:{first.agent_id}")
                    first.memories.append(f"Carried resentment toward {second.name} into this season.")
                    second.memories.append(f"Carried resentment toward {first.name} into this season.")
            elif link.kind == "close_friends" and len(link.agent_ids) == 2:
                first = agent_index.get(link.agent_ids[0])
                second = agent_index.get(link.agent_ids[1])
                if first is not None and second is not None:
                    first.beliefs.append(f"seed:friend:{second.agent_id}")
                    second.beliefs.append(f"seed:friend:{first.agent_id}")
            elif link.kind == "widowed_elder" and len(link.agent_ids) == 1:
                widowed = agent_index.get(link.agent_ids[0])
                if widowed is not None:
                    widowed.grief = max(widowed.grief, 35.0)
                    widowed.memories.append("Still carries grief from a partner lost before the current season.")


def _default_goal_for_stage(stage_of_life: str) -> str:
    if stage_of_life == StageOfLife.CHILD.value:
        return "Stay close to home"
    if stage_of_life == StageOfLife.ADOLESCENT.value:
        return "Help the household"
    return "Maintain daily routine"


def _age_ticks_for_stage(stage_of_life: str) -> int:
    if stage_of_life == StageOfLife.CHILD.value:
        return 250
    if stage_of_life == StageOfLife.ADOLESCENT.value:
        return 700
    if stage_of_life == StageOfLife.ELDER.value:
        return 12_000
    return 2_000
