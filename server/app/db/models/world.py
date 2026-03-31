"""World-level ORM models for events and inventories."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Enum, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.enums import InventoryOwnerType
from app.db.types import JSONB, UUIDArrayType


def enum_column(enum_cls: type, name: str) -> Enum:
    """Create a non-native SQL enum that stores readable string values."""

    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        name=name,
    )


class WorldEvent(UUIDPrimaryKeyMixin, Base):
    """Persistent world event log records."""

    __tablename__ = "world_events"
    __table_args__ = (
        Index("ix_world_events_tick", "tick"),
        Index("ix_world_events_event_type", "event_type"),
    )

    tick: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    actor_ids: Mapped[list[uuid.UUID]] = mapped_column(
        UUIDArrayType(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    target_ids: Mapped[list[uuid.UUID]] = mapped_column(
        UUIDArrayType(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    location_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )


class Inventory(UUIDPrimaryKeyMixin, Base):
    """Persistent inventory entries for agents, buildings, or ground tiles."""

    __tablename__ = "inventories"
    __table_args__ = (
        CheckConstraint("quantity >= 0", name="inventories_quantity_non_negative"),
        Index("ix_inventories_owner", "owner_type", "owner_id"),
        Index("ix_inventories_item_type", "item_type"),
    )

    owner_type: Mapped[InventoryOwnerType] = mapped_column(
        enum_column(InventoryOwnerType, "inventory_owner_type"),
        nullable=False,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), nullable=False)
    item_type: Mapped[str] = mapped_column(Text, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    metadata_json: Mapped[dict[str, object]] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
