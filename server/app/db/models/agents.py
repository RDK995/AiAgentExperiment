"""Agent-centric ORM models for the persistence layer."""

from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, Enum, Float, ForeignKey, Index, Integer, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.db.enums import AgentSex, FacingDirection, GoalSource, GoalStatus, GoalType, StageOfLife
from app.db.types import JSONB


def enum_column(enum_cls: type, name: str) -> Enum:
    """Create a non-native SQL enum that stores readable string values."""

    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=True,
        values_callable=lambda members: [member.value for member in members],
        name=name,
    )


class Agent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Persistent authoritative agent record."""

    __tablename__ = "agents"
    __table_args__ = (
        Index("ix_agents_alive", "alive"),
        Index("ix_agents_household_id", "household_id"),
        Index("ix_agents_home_building_id", "home_building_id"),
    )

    name: Mapped[str] = mapped_column(Text, nullable=False)
    sex: Mapped[AgentSex] = mapped_column(enum_column(AgentSex, "agent_sex"), nullable=False)
    birth_tick: Mapped[int] = mapped_column(nullable=False)
    death_tick: Mapped[int | None] = mapped_column(nullable=True)
    alive: Mapped[bool] = mapped_column(nullable=False, default=True, server_default="true")
    household_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    home_building_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    current_tile_x: Mapped[int] = mapped_column(Integer, nullable=False)
    current_tile_y: Mapped[int] = mapped_column(Integer, nullable=False)
    facing: Mapped[FacingDirection | None] = mapped_column(
        enum_column(FacingDirection, "facing_direction"),
        nullable=True,
    )
    stage_of_life: Mapped[StageOfLife] = mapped_column(
        enum_column(StageOfLife, "stage_of_life"),
        nullable=False,
    )
    biography_summary: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default="",
    )

    traits: Mapped["AgentTrait"] = relationship(back_populates="agent", cascade="all, delete-orphan", uselist=False)
    needs: Mapped["AgentNeed"] = relationship(back_populates="agent", cascade="all, delete-orphan", uselist=False)
    skills: Mapped["AgentSkill"] = relationship(back_populates="agent", cascade="all, delete-orphan", uselist=False)
    goals: Mapped[list["AgentGoal"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    memories: Mapped[list["EpisodicMemory"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    beliefs: Mapped[list["SemanticBelief"]] = relationship(back_populates="agent", cascade="all, delete-orphan")
    outgoing_relationships: Mapped[list["Relationship"]] = relationship(
        back_populates="source_agent",
        foreign_keys="Relationship.source_agent_id",
        cascade="all, delete-orphan",
    )
    incoming_relationships: Mapped[list["Relationship"]] = relationship(
        back_populates="target_agent",
        foreign_keys="Relationship.target_agent_id",
        cascade="all, delete-orphan",
    )


class AgentTrait(Base):
    """Persistent personality and simulation trait values for an agent."""

    __tablename__ = "agent_traits"
    __table_args__ = (
        CheckConstraint("sociability >= 0 AND sociability <= 1", name="agent_traits_sociability_range"),
        CheckConstraint("aggression >= 0 AND aggression <= 1", name="agent_traits_aggression_range"),
        CheckConstraint(
            "conscientiousness >= 0 AND conscientiousness <= 1",
            name="agent_traits_conscientiousness_range",
        ),
        CheckConstraint("curiosity >= 0 AND curiosity <= 1", name="agent_traits_curiosity_range"),
        CheckConstraint(
            "family_orientation >= 0 AND family_orientation <= 1",
            name="agent_traits_family_orientation_range",
        ),
        CheckConstraint(
            "risk_tolerance >= 0 AND risk_tolerance <= 1",
            name="agent_traits_risk_tolerance_range",
        ),
        CheckConstraint("libido >= 0 AND libido <= 1", name="agent_traits_libido_range"),
        CheckConstraint(
            "emotional_stability >= 0 AND emotional_stability <= 1",
            name="agent_traits_emotional_stability_range",
        ),
        CheckConstraint(
            "memory_fidelity >= 0 AND memory_fidelity <= 1",
            name="agent_traits_memory_fidelity_range",
        ),
        CheckConstraint(
            "learning_rate >= 0 AND learning_rate <= 1",
            name="agent_traits_learning_rate_range",
        ),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    sociability: Mapped[float] = mapped_column(Float, nullable=False)
    aggression: Mapped[float] = mapped_column(Float, nullable=False)
    conscientiousness: Mapped[float] = mapped_column(Float, nullable=False)
    curiosity: Mapped[float] = mapped_column(Float, nullable=False)
    family_orientation: Mapped[float] = mapped_column(Float, nullable=False)
    risk_tolerance: Mapped[float] = mapped_column(Float, nullable=False)
    libido: Mapped[float] = mapped_column(Float, nullable=False)
    emotional_stability: Mapped[float] = mapped_column(Float, nullable=False)
    memory_fidelity: Mapped[float] = mapped_column(Float, nullable=False)
    learning_rate: Mapped[float] = mapped_column(Float, nullable=False)

    agent: Mapped[Agent] = relationship(back_populates="traits")


class AgentNeed(Base):
    """Persistent need values for an agent."""

    __tablename__ = "agent_needs"
    __table_args__ = (
        CheckConstraint("hunger >= 0 AND hunger <= 100", name="agent_needs_hunger_range"),
        CheckConstraint("thirst >= 0 AND thirst <= 100", name="agent_needs_thirst_range"),
        CheckConstraint("fatigue >= 0 AND fatigue <= 100", name="agent_needs_fatigue_range"),
        CheckConstraint("warmth >= 0 AND warmth <= 100", name="agent_needs_warmth_range"),
        CheckConstraint("health >= 0 AND health <= 100", name="agent_needs_health_range"),
        CheckConstraint("stress >= 0 AND stress <= 100", name="agent_needs_stress_range"),
        CheckConstraint("loneliness >= 0 AND loneliness <= 100", name="agent_needs_loneliness_range"),
        CheckConstraint("safety >= 0 AND safety <= 100", name="agent_needs_safety_range"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    hunger: Mapped[float] = mapped_column(Float, nullable=False)
    thirst: Mapped[float] = mapped_column(Float, nullable=False)
    fatigue: Mapped[float] = mapped_column(Float, nullable=False)
    warmth: Mapped[float] = mapped_column(Float, nullable=False)
    health: Mapped[float] = mapped_column(Float, nullable=False)
    stress: Mapped[float] = mapped_column(Float, nullable=False)
    loneliness: Mapped[float] = mapped_column(Float, nullable=False)
    safety: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    agent: Mapped[Agent] = relationship(back_populates="needs")


class AgentSkill(Base):
    """Persistent skill levels for an agent."""

    __tablename__ = "agent_skills"
    __table_args__ = (
        CheckConstraint("farming >= 0", name="agent_skills_farming_non_negative"),
        CheckConstraint("fishing >= 0", name="agent_skills_fishing_non_negative"),
        CheckConstraint("gathering >= 0", name="agent_skills_gathering_non_negative"),
        CheckConstraint("cooking >= 0", name="agent_skills_cooking_non_negative"),
        CheckConstraint("crafting >= 0", name="agent_skills_crafting_non_negative"),
        CheckConstraint("caregiving >= 0", name="agent_skills_caregiving_non_negative"),
        CheckConstraint("social >= 0", name="agent_skills_social_non_negative"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    farming: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    fishing: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    gathering: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    cooking: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    crafting: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    caregiving: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    social: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")

    agent: Mapped[Agent] = relationship(back_populates="skills")


class AgentGoal(UUIDPrimaryKeyMixin, Base):
    """Persistent goal records for the cognition and planning systems."""

    __tablename__ = "agent_goals"
    __table_args__ = (
        CheckConstraint("priority >= 0", name="agent_goals_priority_non_negative"),
        CheckConstraint("horizon_days >= 0", name="agent_goals_horizon_days_non_negative"),
        Index("ix_agent_goals_agent_id_status", "agent_id", "status"),
        Index("ix_agent_goals_created_tick", "created_tick"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    goal_type: Mapped[GoalType] = mapped_column(enum_column(GoalType, "goal_type"), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[float] = mapped_column(Float, nullable=False)
    horizon_days: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[GoalStatus] = mapped_column(enum_column(GoalStatus, "goal_status"), nullable=False)
    target_entity_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_entity_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    blocker_summary: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    success_condition: Mapped[dict[str, object]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    source: Mapped[GoalSource] = mapped_column(enum_column(GoalSource, "goal_source"), nullable=False)
    created_tick: Mapped[int] = mapped_column(nullable=False)
    updated_tick: Mapped[int] = mapped_column(nullable=False)

    agent: Mapped[Agent] = relationship(back_populates="goals")
