"""Focused tests for compact agent perception."""

from __future__ import annotations

from datetime import datetime, timezone

from app.db.enums import StageOfLife
from app.agents.perception import PerceptionResult, PerceptionService
from app.engine.world_state import AgentState, ItemStackState, ResourceNodeState, TerrainType, TileState, WorldState


def test_perception_detects_nearby_water_food_and_infants() -> None:
    """Perception should surface compact nearby context without dumping world state."""

    world = WorldState(
        width=4,
        height=4,
        tiles=[
            TileState(x=0, y=0, terrain=TerrainType.GRASS),
            TileState(x=1, y=0, terrain=TerrainType.WATER),
            TileState(x=0, y=1, terrain=TerrainType.PATH),
            TileState(x=1, y=1, terrain=TerrainType.GRASS),
        ],
        agents=[
            AgentState(agent_id="agent-1", name="A", x=0, y=0),
            AgentState(agent_id="agent-2", name="Infant", x=1, y=0, stage_of_life=StageOfLife.INFANT, age_ticks=10),
        ],
        items=[ItemStackState(item_type="berries", x=0, y=1)],
        resources=[ResourceNodeState(resource_type="water", x=1, y=0)],
    )

    result = PerceptionService(radius=2).perceive(
        world,
        world.agents[0],
        datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
    )

    assert isinstance(result, PerceptionResult)
    assert result.visible_agents == ["agent-2"]
    assert result.visible_items == ["berries"]
    assert result.visible_resources == ["water"]
    assert result.nearby_water is True
    assert result.nearby_food is True
    assert result.nearby_infant_ids == ["agent-2"]
    assert (result.nearest_water_x, result.nearest_water_y) == (1, 0)
    assert (result.nearest_food_x, result.nearest_food_y) == (0, 1)
    assert (result.nearest_infant_x, result.nearest_infant_y) == (1, 0)


def test_perception_flags_nearby_threats_compactly() -> None:
    """Threat detection should be a small boolean signal in the perception result."""

    world = WorldState(
        width=3,
        height=3,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(3) for x in range(3)],
        agents=[
            AgentState(agent_id="agent-1", name="A", x=1, y=1),
            AgentState(agent_id="agent-2", name="Threat", x=2, y=1, is_threat=True),
        ],
    )

    result = PerceptionService(radius=2).perceive(
        world,
        world.agents[0],
        datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
    )

    assert result.nearby_threat is True
    assert result.visible_agents == ["agent-2"]


def test_perception_uses_walkable_adjacent_anchor_for_water_tiles() -> None:
    """Water-tile perception should return a walkable interaction anchor, not the water tile itself."""

    world = WorldState(
        width=3,
        height=3,
        tiles=[
            TileState(x=0, y=0, terrain=TerrainType.GRASS),
            TileState(x=1, y=0, terrain=TerrainType.WATER, walkable=False),
            TileState(x=2, y=0, terrain=TerrainType.GRASS),
            TileState(x=0, y=1, terrain=TerrainType.GRASS),
            TileState(x=1, y=1, terrain=TerrainType.GRASS),
            TileState(x=2, y=1, terrain=TerrainType.GRASS),
            TileState(x=0, y=2, terrain=TerrainType.GRASS),
            TileState(x=1, y=2, terrain=TerrainType.GRASS),
            TileState(x=2, y=2, terrain=TerrainType.GRASS),
        ],
        agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1)],
    )

    result = PerceptionService(radius=2).perceive(
        world,
        world.agents[0],
        datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
    )

    assert result.nearby_water is True
    assert (result.nearest_water_x, result.nearest_water_y) in {(0, 0), (2, 0), (1, 1)}


def test_perception_respects_scan_radius_and_stays_compact() -> None:
    """Only local entities should be surfaced, and the result should remain a compact schema."""

    world = WorldState(
        width=6,
        height=6,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(6) for x in range(6)],
        agents=[
            AgentState(agent_id="agent-1", name="Scout", x=1, y=1),
            AgentState(agent_id="agent-2", name="Near Infant", x=2, y=1, stage_of_life=StageOfLife.INFANT),
            AgentState(agent_id="agent-3", name="Far Threat", x=5, y=5, is_threat=True),
        ],
        items=[
            ItemStackState(item_type="berries", x=2, y=1),
            ItemStackState(item_type="meal", x=5, y=4),
        ],
        resources=[
            ResourceNodeState(resource_type="water", x=1, y=2),
            ResourceNodeState(resource_type="berries", x=5, y=5),
        ],
    )

    result = PerceptionService(radius=2).perceive(
        world,
        world.agents[0],
        datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
    )

    dumped = result.model_dump()

    assert result.visible_agents == ["agent-2"]
    assert result.visible_items == ["berries"]
    assert result.visible_resources == ["water"]
    assert result.nearby_food is True
    assert result.nearby_threat is False
    assert result.nearby_infant_ids == ["agent-2"]
    assert "world" not in dumped
    assert "tiles" not in dumped
    assert "agents" not in dumped
    assert "items" not in dumped
    assert "resources" not in dumped


def test_perception_surfaces_partner_bed_and_environment_context() -> None:
    """Perception should expose relationship, rest, and environment hints in compact form."""

    world = WorldState(
        width=3,
        height=3,
        weather="rain",
        tiles=[
            TileState(x=0, y=0, terrain=TerrainType.GRASS),
            TileState(x=1, y=0, terrain=TerrainType.PATH),
            TileState(x=2, y=0, terrain=TerrainType.GRASS),
            TileState(x=0, y=1, terrain=TerrainType.GRASS),
            TileState(x=1, y=1, terrain=TerrainType.PATH),
            TileState(x=2, y=1, terrain=TerrainType.GRASS),
            TileState(x=0, y=2, terrain=TerrainType.GRASS),
            TileState(x=1, y=2, terrain=TerrainType.GRASS),
            TileState(x=2, y=2, terrain=TerrainType.GRASS),
        ],
        agents=[
            AgentState(agent_id="agent-1", name="A", x=1, y=1, partner_id="agent-2"),
            AgentState(agent_id="agent-2", name="Partner", x=2, y=1),
        ],
        items=[ItemStackState(item_type="bed", x=1, y=2)],
    )

    result = PerceptionService(radius=2).perceive(
        world,
        world.agents[0],
        datetime(2000, 1, 1, 21, 0, tzinfo=timezone.utc),
    )

    assert result.visible_partner is True
    assert result.nearby_bed is True
    assert result.terrain == "path"
    assert result.weather == "rain"
    assert result.sim_hour == 21


def test_perception_uses_deterministic_tie_break_for_nearest_food() -> None:
    """Equidistant compact food targets should resolve in a stable deterministic order."""

    world = WorldState(
        width=4,
        height=4,
        tiles=[TileState(x=x, y=y, terrain=TerrainType.GRASS) for y in range(4) for x in range(4)],
        agents=[AgentState(agent_id="agent-1", name="A", x=1, y=1)],
        items=[
            ItemStackState(item_type="berries", x=0, y=1),
            ItemStackState(item_type="berries", x=1, y=0),
        ],
    )

    result = PerceptionService(radius=2).perceive(
        world,
        world.agents[0],
        datetime(2000, 1, 1, 8, 0, tzinfo=timezone.utc),
    )

    assert (result.nearest_food_x, result.nearest_food_y) == (0, 1)
