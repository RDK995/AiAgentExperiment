"""Pure simulation rule helpers for authoritative movement and action legality."""

from __future__ import annotations

from app.engine.world_state import AgentState, TileState, WorldState


def get_tile_at(world: WorldState, x: int, y: int) -> TileState | None:
    """Return the authoritative tile at the requested position, if present."""

    for tile in world.tiles:
        if tile.x == x and tile.y == y:
            return tile
    return None


def is_position_within_bounds(world: WorldState, x: int, y: int) -> bool:
    """Check whether a position is inside the world grid."""

    return 0 <= x < world.width and 0 <= y < world.height


def is_movement_valid(world: WorldState, x: int, y: int) -> bool:
    """A move is valid only if the destination exists and is walkable."""

    if not is_position_within_bounds(world, x, y):
        return False

    tile = get_tile_at(world, x, y)
    return tile is not None and tile.walkable


def is_action_legal(
    world: WorldState,
    agent: AgentState,
    action: str,
    target_x: int | None = None,
    target_y: int | None = None,
) -> bool:
    """Validate a minimal set of authoritative actions for the current prototype."""

    if action == "idle":
        return True

    if action != "move":
        return False

    if target_x is None or target_y is None:
        return False

    if not is_movement_valid(world, target_x, target_y):
        return False

    manhattan_distance = abs(target_x - agent.x) + abs(target_y - agent.y)
    return manhattan_distance == 1
