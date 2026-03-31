"""Shared pytest fixtures for backend tests."""

from collections.abc import Iterator
from pathlib import Path
import sys

import pytest
from fastapi.testclient import TestClient

SERVER_ROOT = Path(__file__).resolve().parents[1]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from app.main import create_app
from app.engine.world_state import AgentState, TerrainType, TileState, WorldState


@pytest.fixture
def client() -> Iterator[TestClient]:
    """Create a fresh FastAPI test client with an isolated runtime."""

    app = create_app()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def simple_world() -> WorldState:
    """Small deterministic world fixture for simulation-core unit tests."""

    return WorldState(
        width=4,
        height=3,
        tiles=[
            TileState(x=0, y=0, terrain=TerrainType.GRASS, walkable=True),
            TileState(x=1, y=0, terrain=TerrainType.GRASS, walkable=True),
            TileState(x=2, y=0, terrain=TerrainType.WATER, walkable=False),
            TileState(x=3, y=0, terrain=TerrainType.GRASS, walkable=True),
            TileState(x=0, y=1, terrain=TerrainType.PATH, walkable=True),
            TileState(x=1, y=1, terrain=TerrainType.PATH, walkable=True),
            TileState(x=2, y=1, terrain=TerrainType.PATH, walkable=True),
            TileState(x=3, y=1, terrain=TerrainType.PATH, walkable=True),
            TileState(x=0, y=2, terrain=TerrainType.GRASS, walkable=True),
            TileState(x=1, y=2, terrain=TerrainType.GRASS, walkable=True),
            TileState(x=2, y=2, terrain=TerrainType.GRASS, walkable=True),
            TileState(x=3, y=2, terrain=TerrainType.GRASS, walkable=True),
        ],
        agents=[
            AgentState(
                agent_id="agent-1",
                name="Villager 1",
                x=1,
                y=1,
            )
        ],
    )
