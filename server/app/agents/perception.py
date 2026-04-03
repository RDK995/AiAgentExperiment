"""Deterministic perception service for the agent fast loop."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable

from pydantic import BaseModel, ConfigDict, Field

from app.db.enums import StageOfLife
from app.engine.rules.simulation_rules import is_movement_valid
from app.engine.world_state import AgentState, WorldState


class PerceptionResult(BaseModel):
    """Compact local context consumed by utility scoring and planning."""

    model_config = ConfigDict(extra="forbid")

    visible_agents: list[str] = Field(default_factory=list)
    visible_items: list[str] = Field(default_factory=list)
    visible_resources: list[str] = Field(default_factory=list)
    nearby_water: bool = False
    nearby_food: bool = False
    nearby_threat: bool = False
    nearby_infant_ids: list[str] = Field(default_factory=list)
    nearest_water_x: int | None = None
    nearest_water_y: int | None = None
    nearest_food_x: int | None = None
    nearest_food_y: int | None = None
    nearest_infant_x: int | None = None
    nearest_infant_y: int | None = None
    visible_partner: bool = False
    nearby_bed: bool = False
    terrain: str = "grass"
    weather: str = "clear"
    sim_hour: int = 0


class PerceptionService:
    """Build a compact local view of the authoritative world for an agent."""

    def __init__(self, radius: int = 2) -> None:
        self._radius = radius

    def perceive(self, world: WorldState, agent: AgentState, now: datetime) -> PerceptionResult:
        """Scan local tiles, agents, items, and resources within a compact radius."""

        visible_agents: list[str] = []
        nearby_infant_ids: list[str] = []
        infant_targets: list[tuple[int, int]] = []
        visible_partner = False
        nearby_threat = False

        for other in world.agents:
            if other.agent_id == agent.agent_id or not other.alive:
                continue
            if _distance(agent.x, agent.y, other.x, other.y) > self._radius:
                continue

            visible_agents.append(other.agent_id)
            if other.stage_of_life is StageOfLife.INFANT:
                nearby_infant_ids.append(other.agent_id)
                infant_targets.append((other.x, other.y))
            if agent.partner_id and other.agent_id == agent.partner_id:
                visible_partner = True
            if other.is_threat:
                nearby_threat = True

        visible_items = [
            item.item_type
            for item in world.items
            if _distance(agent.x, agent.y, item.x, item.y) <= self._radius
        ]
        visible_resources = [
            resource.resource_type
            for resource in world.resources
            if _distance(agent.x, agent.y, resource.x, resource.y) <= self._radius
        ]
        food_targets = [
            (item.x, item.y)
            for item in world.items
            if item.item_type in _FOOD_ITEM_TYPES and _distance(agent.x, agent.y, item.x, item.y) <= self._radius
        ]
        food_targets.extend(
            (resource.x, resource.y)
            for resource in world.resources
            if resource.resource_type in _FOOD_RESOURCE_TYPES
            and _distance(agent.x, agent.y, resource.x, resource.y) <= self._radius
        )
        water_targets = [
            (resource.x, resource.y)
            for resource in world.resources
            if resource.resource_type == "water" and _distance(agent.x, agent.y, resource.x, resource.y) <= self._radius
        ]
        if not water_targets:
            water_targets.extend(
                adjacent
                for tile in world.tiles
                if tile.terrain.value == "water" and _distance(agent.x, agent.y, tile.x, tile.y) <= self._radius
                for adjacent in _adjacent_walkable_positions(world, tile.x, tile.y, agent.agent_id)
            )

        nearby_water = any(
            tile.terrain.value == "water"
            and _distance(agent.x, agent.y, tile.x, tile.y) <= self._radius
            for tile in world.tiles
        ) or any(resource == "water" for resource in visible_resources)
        nearby_food = any(item in _FOOD_ITEM_TYPES for item in visible_items) or any(
            resource in _FOOD_RESOURCE_TYPES for resource in visible_resources
        )
        nearby_bed = any(item == "bed" for item in visible_items)
        nearby_threat = nearby_threat or any(
            resource.threat_level > 0
            and _distance(agent.x, agent.y, resource.x, resource.y) <= self._radius
            for resource in world.resources
        )
        nearest_water_x, nearest_water_y = _nearest_position(agent.x, agent.y, water_targets)
        nearest_food_x, nearest_food_y = _nearest_position(agent.x, agent.y, food_targets)
        nearest_infant_x, nearest_infant_y = _nearest_position(agent.x, agent.y, infant_targets)

        return PerceptionResult(
            visible_agents=visible_agents,
            visible_items=visible_items,
            visible_resources=visible_resources,
            nearby_water=nearby_water,
            nearby_food=nearby_food,
            nearby_threat=nearby_threat,
            nearby_infant_ids=nearby_infant_ids,
            nearest_water_x=nearest_water_x,
            nearest_water_y=nearest_water_y,
            nearest_food_x=nearest_food_x,
            nearest_food_y=nearest_food_y,
            nearest_infant_x=nearest_infant_x,
            nearest_infant_y=nearest_infant_y,
            visible_partner=visible_partner,
            nearby_bed=nearby_bed,
            terrain=world.terrain_at(agent.x, agent.y),
            weather=world.weather,
            sim_hour=now.hour,
        )


_FOOD_ITEM_TYPES = {"food", "berries", "fruit", "meal"}
_FOOD_RESOURCE_TYPES = {"berries", "field", "orchard", "fish"}


def _distance(x1: int, y1: int, x2: int, y2: int) -> int:
    """Return Manhattan distance for local deterministic perception scans."""

    return abs(x1 - x2) + abs(y1 - y2)


def _nearest_position(agent_x: int, agent_y: int, positions: Iterable[tuple[int, int]]) -> tuple[int | None, int | None]:
    """Return the nearest compact target position from a candidate collection."""

    ordered = sorted(positions, key=lambda item: (_distance(agent_x, agent_y, item[0], item[1]), item[0], item[1]))
    if not ordered:
        return (None, None)
    return ordered[0]


def _adjacent_walkable_positions(
    world: WorldState,
    x: int,
    y: int,
    ignore_agent_id: str,
) -> list[tuple[int, int]]:
    """Return walkable neighboring positions for interacting with nearby terrain features."""

    candidates = [(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)]
    return [
        (candidate_x, candidate_y)
        for candidate_x, candidate_y in candidates
        if is_movement_valid(world, candidate_x, candidate_y, ignore_agent_id=ignore_agent_id)
    ]
