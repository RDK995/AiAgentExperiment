"""Unit tests for deterministic world-seed loading and expansion."""

import json
from pathlib import Path

from app.db.enums import StageOfLife
from app.engine.world_state import TerrainType
from app.services.world_seed_service import WorldSeedService


def test_v1_world_seed_definition_loads_expected_population_layout_and_social_links() -> None:
    """The fixed v1 seed should expand into a stable presentation/debug definition."""

    seed = WorldSeedService().load_seed_definition("v1_village")

    assert seed.seed_id == "v1_village"
    assert seed.world.width == 64
    assert seed.world.height == 64
    assert len(seed.world.tiles) == 64 * 64
    assert len(seed.world.structures) == 15
    assert len(seed.world.markers) == 3
    assert len(seed.agents) == 20
    assert len(seed.households) == 4
    assert len(seed.social_links) == 6
    assert sum(1 for agent in seed.agents if agent.stage_of_life == StageOfLife.ADULT.value) == 12
    assert sum(1 for agent in seed.agents if agent.stage_of_life == StageOfLife.ADOLESCENT.value) == 4
    assert sum(1 for agent in seed.agents if agent.stage_of_life == StageOfLife.CHILD.value) == 4
    assert [link.kind for link in seed.social_links].count("bonded_pair") == 2


def test_v1_world_seed_builds_runtime_state_with_seeded_tiles_partners_and_social_memory() -> None:
    """The backend seed builder should produce authoritative runtime state from the shared seed file."""

    world = WorldSeedService().build_world_state("v1_village")

    row_zero_terrain = {tile.terrain for tile in world.tiles if tile.y == 0 and tile.x < 60}
    east_edge_terrain = {tile.terrain for tile in world.tiles if tile.x >= 60}
    agents_by_id = {agent.agent_id: agent for agent in world.agents}

    assert world.width == 64
    assert world.height == 64
    assert len(world.agents) == 20
    assert row_zero_terrain == {TerrainType.FOREST}
    assert east_edge_terrain == {TerrainType.WATER}
    assert agents_by_id["agent-1"].partner_id == "agent-2"
    assert agents_by_id["agent-2"].partner_id == "agent-1"
    assert any(memory.startswith("Carried resentment") for memory in agents_by_id["agent-5"].memories)
    assert "seed:friend:agent-10" in agents_by_id["agent-6"].beliefs


def test_v1_world_seed_has_required_landmarks_population_shape_and_social_roles() -> None:
    """The fixed seed should preserve the intended village layout and starting social structure."""

    seed = WorldSeedService().load_seed_definition("v1_village")

    structures_by_type = {}
    for structure in seed.world.structures:
        structures_by_type[structure.structure_type] = structures_by_type.get(structure.structure_type, 0) + 1

    markers_by_type = {}
    for marker in seed.world.markers:
        markers_by_type[marker.marker_type] = markers_by_type.get(marker.marker_type, 0) + 1

    adults = [agent for agent in seed.agents if agent.stage_of_life == StageOfLife.ADULT.value]
    adolescents = [agent for agent in seed.agents if agent.stage_of_life == StageOfLife.ADOLESCENT.value]
    children = [agent for agent in seed.agents if agent.stage_of_life == StageOfLife.CHILD.value]
    roles = [agent.role for agent in seed.agents if agent.role is not None]
    social_kinds = [link.kind for link in seed.social_links]

    assert structures_by_type == {
        "village_center": 1,
        "house": 6,
        "well": 1,
        "farm_plot": 4,
        "storage_hut": 1,
        "cooking_area": 1,
        "graveyard": 1,
    }
    assert markers_by_type == {
        "forest": 1,
        "berries": 1,
        "river_edge": 1,
    }
    assert seed.world.markers[0].marker_type == "forest"
    assert seed.world.markers[0].y < 10
    assert seed.world.markers[1].marker_type == "berries"
    assert seed.world.markers[1].x < 10
    assert len(adults) == 12
    assert len(adolescents) == 4
    assert len(children) == 4
    assert len(seed.households) == 4
    assert roles.count("bonded_pair") == 4
    assert roles.count("widowed_elder") == 1
    assert social_kinds.count("bonded_pair") == 2
    assert social_kinds.count("widowed_elder") == 1
    assert social_kinds.count("rival_pair") == 1
    assert social_kinds.count("close_friends") == 2


def test_v1_world_seed_references_are_consistent_and_repeatable() -> None:
    """Loading the shared seed twice should be deterministic with internally consistent references."""

    service = WorldSeedService()
    first = service.load_seed_definition("v1_village")
    second = service.load_seed_definition("v1_village")

    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    structure_ids = {structure.structure_id for structure in first.world.structures}
    household_ids = {household.household_id for household in first.households}
    agent_ids = {agent.agent_id for agent in first.agents}
    agents_by_id = {agent.agent_id: agent for agent in first.agents}

    assert len(structure_ids) == len(first.world.structures)
    assert len(agent_ids) == len(first.agents)
    assert len(household_ids) == len(first.households)

    for household in first.households:
        assert household.home_structure_id in structure_ids
        assert set(household.member_ids) <= agent_ids
        for member_id in household.member_ids:
            assert agents_by_id[member_id].household_id == household.household_id
            assert agents_by_id[member_id].home_structure_id == household.home_structure_id

    for agent in first.agents:
        assert agent.household_id in household_ids
        assert agent.home_structure_id in structure_ids
        partner_id = agent.partner_id
        if partner_id is None:
            continue
        assert partner_id in agent_ids
        assert agents_by_id[partner_id].partner_id == agent.agent_id

    for social_link in first.social_links:
        assert set(social_link.agent_ids) <= agent_ids


def test_v1_world_seed_raw_file_is_complete_and_matches_loader_expectations() -> None:
    """The shared JSON seed file should remain structurally complete for backend and Godot consumers."""

    seed_path = (
        Path(__file__).resolve().parents[3]
        / "client-godot"
        / "data"
        / "world_seeds"
        / "v1_village_seed.json"
    )
    raw = json.loads(seed_path.read_text(encoding="utf-8"))

    assert raw["seed_id"] == "v1_village"
    assert set(raw.keys()) == {"seed_id", "world", "households", "agents", "social_links"}
    assert raw["world"]["width"] == 64
    assert raw["world"]["height"] == 64
    assert len(raw["world"]["terrain_regions"]) >= 4
    assert len(raw["world"]["structures"]) == 15
    assert len(raw["world"]["markers"]) == 3
    assert len(raw["agents"]) == 20
    assert len(raw["households"]) == 4
    assert len(raw["social_links"]) == 6
