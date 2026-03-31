"""Repository helpers for world-level persistence records."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from sqlalchemy.orm import Session

from app.db.models import Inventory, WorldEvent


@dataclass(slots=True)
class WorldEventCreateParams:
    """Parameters for creating a persistent world event record."""

    tick: int
    event_type: str
    actor_ids: list[uuid.UUID] = field(default_factory=list)
    target_ids: list[uuid.UUID] = field(default_factory=list)
    location_x: int | None = None
    location_y: int | None = None
    payload: dict[str, object] = field(default_factory=dict)


class WorldRepository:
    """Persistence helper for world events and inventories."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add_world_event(self, world_event: WorldEvent) -> WorldEvent:
        """Persist a world event."""

        self._session.add(world_event)
        self._session.flush()
        return world_event

    def create_world_event(self, params: WorldEventCreateParams) -> WorldEvent:
        """Create and persist a world event row."""

        world_event = WorldEvent(
            tick=params.tick,
            event_type=params.event_type,
            actor_ids=params.actor_ids,
            target_ids=params.target_ids,
            location_x=params.location_x,
            location_y=params.location_y,
            payload=params.payload,
        )
        return self.add_world_event(world_event)

    def add_inventory_entry(self, inventory: Inventory) -> Inventory:
        """Persist an inventory row."""

        self._session.add(inventory)
        self._session.flush()
        return inventory
