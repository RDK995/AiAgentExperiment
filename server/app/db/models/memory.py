"""Memory and belief ORM models for persistent cognition state."""

from __future__ import annotations

import uuid

from sqlalchemy import CheckConstraint, Float, ForeignKey, Index, Integer, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, UUIDPrimaryKeyMixin
from app.db.types import UUIDArrayType, Vector1536


class EpisodicMemory(UUIDPrimaryKeyMixin, Base):
    """Persistent episodic memory records for an agent."""

    __tablename__ = "episodic_memories"
    __table_args__ = (
        CheckConstraint("decay_rate >= 0", name="episodic_memories_decay_rate_non_negative"),
        Index("ix_episodic_memories_agent_id_tick", "agent_id", "tick"),
        Index("ix_episodic_memories_agent_id_archived_salience", "agent_id", "archived", "salience"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    tick: Mapped[int] = mapped_column(nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    location_x: Mapped[int | None] = mapped_column(Integer, nullable=True)
    location_y: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    valence: Mapped[float] = mapped_column(Float, nullable=False)
    salience: Mapped[float] = mapped_column(Float, nullable=False)
    participant_ids: Mapped[list[uuid.UUID]] = mapped_column(
        UUIDArrayType(),
        nullable=False,
        default=list,
        server_default="[]",
    )
    decay_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.01, server_default="0.01")
    archived: Mapped[bool] = mapped_column(nullable=False, default=False, server_default="false")

    agent: Mapped["Agent"] = relationship(back_populates="memories")
    embedding: Mapped["MemoryEmbedding | None"] = relationship(
        back_populates="memory",
        cascade="all, delete-orphan",
        uselist=False,
    )


class SemanticBelief(UUIDPrimaryKeyMixin, Base):
    """Persistent semantic beliefs for an agent."""

    __tablename__ = "semantic_beliefs"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="semantic_beliefs_confidence_range"),
        CheckConstraint("evidence_count >= 1", name="semantic_beliefs_evidence_count_positive"),
        Index("ix_semantic_beliefs_agent_subject", "agent_id", "subject_type", "subject_id"),
    )

    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    subject_type: Mapped[str] = mapped_column(Text, nullable=False)
    subject_id: Mapped[uuid.UUID | None] = mapped_column(Uuid(as_uuid=True), nullable=True)
    predicate: Mapped[str] = mapped_column(Text, nullable=False)
    object_value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    last_supported_tick: Mapped[int] = mapped_column(nullable=False)

    agent: Mapped["Agent"] = relationship(back_populates="beliefs")


class MemoryEmbedding(Base):
    """Vector embedding storage for episodic memories."""

    __tablename__ = "memory_embeddings"
    __table_args__ = (Index("ix_memory_embeddings_agent_id", "agent_id"),)

    memory_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("episodic_memories.id", ondelete="CASCADE"),
        primary_key=True,
    )
    agent_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("agents.id", ondelete="CASCADE"),
        nullable=False,
    )
    embedding: Mapped[list[float]] = mapped_column(Vector1536(), nullable=False)

    memory: Mapped[EpisodicMemory] = relationship(back_populates="embedding")
