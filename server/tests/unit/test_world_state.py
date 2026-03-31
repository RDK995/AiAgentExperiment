"""Unit tests for authoritative world state bootstrap and agent rules."""

from app.engine.world_state import AgentState, TerrainType, build_initial_world_state


def test_build_initial_world_state_creates_expected_grid_and_path_row() -> None:
    """The bootstrap world should be deterministic and tile-complete."""

    width = 8
    height = 6
    initial_agent_count = 3

    world = build_initial_world_state(
        width=width,
        height=height,
        initial_agent_count=initial_agent_count,
    )

    assert world.width == width
    assert world.height == height
    assert world.tick == 0
    assert len(world.tiles) == width * height
    assert len(world.agents) == initial_agent_count

    center_y = height // 2
    center_row_tiles = [tile for tile in world.tiles if tile.y == center_y]
    off_row_tiles = [tile for tile in world.tiles if tile.y != center_y]

    assert all(tile.terrain == TerrainType.PATH for tile in center_row_tiles)
    assert all(tile.terrain == TerrainType.GRASS for tile in off_row_tiles)
    assert all(agent.y == center_y for agent in world.agents)
    assert [agent.agent_id for agent in world.agents] == [
        "agent-1",
        "agent-2",
        "agent-3",
    ]


def test_agent_advance_needs_is_deterministic_and_clamped() -> None:
    """Need updates should stay bounded inside authoritative simulation rules."""

    agent = AgentState(
        agent_id="agent-1",
        name="Villager 1",
        x=2,
        y=3,
        hunger=99.5,
        thirst=99.0,
        fatigue=99.8,
    )

    agent.advance_needs()

    assert agent.hunger == 100.0
    assert agent.thirst == 100.0
    assert agent.fatigue == 100.0
