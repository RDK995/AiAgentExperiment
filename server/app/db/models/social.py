"""Social-system ORM models for pair bonds, kinship, and pregnancy."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Enum, Float, ForeignKey, Index, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.enums import KinshipType, PairBondState, PregnancyStatus


def enum_column(enum_cls: type, name: str) -> Enum:
    """Create a non-native SQL enum that stores readable string values."""

    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        name=name,
    )


class Relationship(UUIDPrimaryKeyMixin, Base):
    """Directed social relationship values between two agents."""

    __tablename__ = "relationships"
    __table_args__ = (
        UniqueConstraint("source_agent_id", "target_agent_id", name="uq_relationships_source_target"),
        CheckConstraint("source_agent_id != target_agent_id", name="relationships_distinct_agents"),
        Index("ix_relationships_source_agent_id", "source_agent_id"),
        Index("ix_relationships_target_agent_id", "target_agent_id"),
    )

    source_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    target_agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    familiarity: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    trust: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    attraction: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    resentment: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    admiration: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    fear: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    obligation: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    dependency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    kinship_type: Mapped[KinshipType | None] = mapped_column(
        enum_column(KinshipType, "kinship_type"),
        nullable=True,
    )
    last_interaction_tick: Mapped[int | None] = mapped_column(nullable=True)

    source_agent: Mapped["Agent"] = relationship(
        back_populates="outgoing_relationships",
        foreign_keys=[source_agent_id],
    )
    target_agent: Mapped["Agent"] = relationship(
        back_populates="incoming_relationships",
        foreign_keys=[target_agent_id],
    )


class PairBond(UUIDPrimaryKeyMixin, Base):
    """Pair-bond records between two agents."""

    __tablename__ = "pair_bonds"
    __table_args__ = (
        CheckConstraint("agent_a_id != agent_b_id", name="pair_bonds_distinct_agents"),
        CheckConstraint("bond_strength >= 0", name="pair_bonds_bond_strength_non_negative"),
        Index("ix_pair_bonds_agent_a_id", "agent_a_id"),
        Index("ix_pair_bonds_agent_b_id", "agent_b_id"),
        Index("ix_pair_bonds_state", "state"),
    )

    agent_a_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
    agent_b_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id", ondelete="CASCADE"))
    state: Mapped[PairBondState] = mapped_column(enum_column(PairBondState, "pair_bond_state"), nullable=False)
    bond_strength: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    started_tick: Mapped[int] = mapped_column(nullable=False)
    ended_tick: Mapped[int | None] = mapped_column(nullable=True)


class Pregnancy(UUIDPrimaryKeyMixin, Base):
    """Pregnancy records tied to agents."""

    __tablename__ = "pregnancies"
    __table_args__ = (
        Index("ix_pregnancies_mother_id_status", "mother_id", "status"),
        Index("ix_pregnancies_expected_birth_tick", "expected_birth_tick"),
    )

    mother_id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=False)
    father_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), ForeignKey("agents.id"), nullable=True)
    started_tick: Mapped[int] = mapped_column(nullable=False)
    expected_birth_tick: Mapped[int] = mapped_column(nullable=False)
    status: Mapped[PregnancyStatus] = mapped_column(
        enum_column(PregnancyStatus, "pregnancy_status"),
        nullable=False,
    )
