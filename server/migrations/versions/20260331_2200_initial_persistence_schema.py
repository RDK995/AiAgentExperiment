"""Initial persistent simulation schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.db.types import UUIDArrayType, Vector1536

revision = "20260331_2200"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgresql = bind.dialect.name == "postgresql"

    if is_postgresql:
        op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    agent_sex = sa.Enum("female", "male", "intersex", name="agent_sex", native_enum=False)
    facing_direction = sa.Enum("north", "east", "south", "west", name="facing_direction", native_enum=False)
    stage_of_life = sa.Enum(
        "infant",
        "child",
        "adolescent",
        "adult",
        "elder",
        name="stage_of_life",
        native_enum=False,
    )
    kinship_type = sa.Enum("none", "parent", "child", "sibling", "cousin", name="kinship_type", native_enum=False)
    pair_bond_state = sa.Enum("courting", "bonded", "separated", name="pair_bond_state", native_enum=False)
    pregnancy_status = sa.Enum(
        "active",
        "ended",
        "miscarriage",
        "birth",
        name="pregnancy_status",
        native_enum=False,
    )
    goal_type = sa.Enum("family", "status", "safety", "wealth", "exploration", name="goal_type", native_enum=False)
    goal_status = sa.Enum(
        "active",
        "paused",
        "completed",
        "abandoned",
        name="goal_status",
        native_enum=False,
    )
    goal_source = sa.Enum("seeded", "reflection", "inherited", name="goal_source", native_enum=False)
    inventory_owner_type = sa.Enum(
        "agent",
        "building",
        "ground",
        name="inventory_owner_type",
        native_enum=False,
    )

    op.create_table(
        "agents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sex", agent_sex, nullable=False),
        sa.Column("birth_tick", sa.BigInteger(), nullable=False),
        sa.Column("death_tick", sa.BigInteger(), nullable=True),
        sa.Column("alive", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("household_id", sa.Uuid(), nullable=True),
        sa.Column("home_building_id", sa.Uuid(), nullable=True),
        sa.Column("current_tile_x", sa.Integer(), nullable=False),
        sa.Column("current_tile_y", sa.Integer(), nullable=False),
        sa.Column("facing", facing_direction, nullable=True),
        sa.Column("stage_of_life", stage_of_life, nullable=False),
        sa.Column("biography_summary", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agents")),
    )
    op.create_index("ix_agents_alive", "agents", ["alive"])
    op.create_index("ix_agents_household_id", "agents", ["household_id"])
    op.create_index("ix_agents_home_building_id", "agents", ["home_building_id"])

    op.create_table(
        "agent_traits",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("sociability", sa.Float(), nullable=False),
        sa.Column("aggression", sa.Float(), nullable=False),
        sa.Column("conscientiousness", sa.Float(), nullable=False),
        sa.Column("curiosity", sa.Float(), nullable=False),
        sa.Column("family_orientation", sa.Float(), nullable=False),
        sa.Column("risk_tolerance", sa.Float(), nullable=False),
        sa.Column("libido", sa.Float(), nullable=False),
        sa.Column("emotional_stability", sa.Float(), nullable=False),
        sa.Column("memory_fidelity", sa.Float(), nullable=False),
        sa.Column("learning_rate", sa.Float(), nullable=False),
        sa.CheckConstraint("sociability >= 0 AND sociability <= 1", name=op.f("ck_agent_traits_agent_traits_sociability_range")),
        sa.CheckConstraint("aggression >= 0 AND aggression <= 1", name=op.f("ck_agent_traits_agent_traits_aggression_range")),
        sa.CheckConstraint(
            "conscientiousness >= 0 AND conscientiousness <= 1",
            name=op.f("ck_agent_traits_agent_traits_conscientiousness_range"),
        ),
        sa.CheckConstraint("curiosity >= 0 AND curiosity <= 1", name=op.f("ck_agent_traits_agent_traits_curiosity_range")),
        sa.CheckConstraint(
            "family_orientation >= 0 AND family_orientation <= 1",
            name=op.f("ck_agent_traits_agent_traits_family_orientation_range"),
        ),
        sa.CheckConstraint(
            "risk_tolerance >= 0 AND risk_tolerance <= 1",
            name=op.f("ck_agent_traits_agent_traits_risk_tolerance_range"),
        ),
        sa.CheckConstraint("libido >= 0 AND libido <= 1", name=op.f("ck_agent_traits_agent_traits_libido_range")),
        sa.CheckConstraint(
            "emotional_stability >= 0 AND emotional_stability <= 1",
            name=op.f("ck_agent_traits_agent_traits_emotional_stability_range"),
        ),
        sa.CheckConstraint(
            "memory_fidelity >= 0 AND memory_fidelity <= 1",
            name=op.f("ck_agent_traits_agent_traits_memory_fidelity_range"),
        ),
        sa.CheckConstraint(
            "learning_rate >= 0 AND learning_rate <= 1",
            name=op.f("ck_agent_traits_agent_traits_learning_rate_range"),
        ),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_agent_traits_agent_id_agents")),
        sa.PrimaryKeyConstraint("agent_id", name=op.f("pk_agent_traits")),
    )

    op.create_table(
        "agent_needs",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("hunger", sa.Float(), nullable=False),
        sa.Column("thirst", sa.Float(), nullable=False),
        sa.Column("fatigue", sa.Float(), nullable=False),
        sa.Column("warmth", sa.Float(), nullable=False),
        sa.Column("health", sa.Float(), nullable=False),
        sa.Column("stress", sa.Float(), nullable=False),
        sa.Column("loneliness", sa.Float(), nullable=False),
        sa.Column("safety", sa.Float(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("hunger >= 0 AND hunger <= 100", name=op.f("ck_agent_needs_agent_needs_hunger_range")),
        sa.CheckConstraint("thirst >= 0 AND thirst <= 100", name=op.f("ck_agent_needs_agent_needs_thirst_range")),
        sa.CheckConstraint("fatigue >= 0 AND fatigue <= 100", name=op.f("ck_agent_needs_agent_needs_fatigue_range")),
        sa.CheckConstraint("warmth >= 0 AND warmth <= 100", name=op.f("ck_agent_needs_agent_needs_warmth_range")),
        sa.CheckConstraint("health >= 0 AND health <= 100", name=op.f("ck_agent_needs_agent_needs_health_range")),
        sa.CheckConstraint("stress >= 0 AND stress <= 100", name=op.f("ck_agent_needs_agent_needs_stress_range")),
        sa.CheckConstraint("loneliness >= 0 AND loneliness <= 100", name=op.f("ck_agent_needs_agent_needs_loneliness_range")),
        sa.CheckConstraint("safety >= 0 AND safety <= 100", name=op.f("ck_agent_needs_agent_needs_safety_range")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_agent_needs_agent_id_agents")),
        sa.PrimaryKeyConstraint("agent_id", name=op.f("pk_agent_needs")),
    )

    op.create_table(
        "agent_skills",
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("farming", sa.Float(), server_default="0", nullable=False),
        sa.Column("fishing", sa.Float(), server_default="0", nullable=False),
        sa.Column("gathering", sa.Float(), server_default="0", nullable=False),
        sa.Column("cooking", sa.Float(), server_default="0", nullable=False),
        sa.Column("crafting", sa.Float(), server_default="0", nullable=False),
        sa.Column("caregiving", sa.Float(), server_default="0", nullable=False),
        sa.Column("social", sa.Float(), server_default="0", nullable=False),
        sa.CheckConstraint("farming >= 0", name=op.f("ck_agent_skills_agent_skills_farming_non_negative")),
        sa.CheckConstraint("fishing >= 0", name=op.f("ck_agent_skills_agent_skills_fishing_non_negative")),
        sa.CheckConstraint("gathering >= 0", name=op.f("ck_agent_skills_agent_skills_gathering_non_negative")),
        sa.CheckConstraint("cooking >= 0", name=op.f("ck_agent_skills_agent_skills_cooking_non_negative")),
        sa.CheckConstraint("crafting >= 0", name=op.f("ck_agent_skills_agent_skills_crafting_non_negative")),
        sa.CheckConstraint("caregiving >= 0", name=op.f("ck_agent_skills_agent_skills_caregiving_non_negative")),
        sa.CheckConstraint("social >= 0", name=op.f("ck_agent_skills_agent_skills_social_non_negative")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_agent_skills_agent_id_agents")),
        sa.PrimaryKeyConstraint("agent_id", name=op.f("pk_agent_skills")),
    )

    op.create_table(
        "relationships",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("source_agent_id", sa.Uuid(), nullable=False),
        sa.Column("target_agent_id", sa.Uuid(), nullable=False),
        sa.Column("familiarity", sa.Float(), server_default="0", nullable=False),
        sa.Column("trust", sa.Float(), server_default="0", nullable=False),
        sa.Column("attraction", sa.Float(), server_default="0", nullable=False),
        sa.Column("resentment", sa.Float(), server_default="0", nullable=False),
        sa.Column("admiration", sa.Float(), server_default="0", nullable=False),
        sa.Column("fear", sa.Float(), server_default="0", nullable=False),
        sa.Column("obligation", sa.Float(), server_default="0", nullable=False),
        sa.Column("dependency", sa.Float(), server_default="0", nullable=False),
        sa.Column("kinship_type", kinship_type, nullable=True),
        sa.Column("last_interaction_tick", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("source_agent_id != target_agent_id", name=op.f("ck_relationships_relationships_distinct_agents")),
        sa.ForeignKeyConstraint(["source_agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_relationships_source_agent_id_agents")),
        sa.ForeignKeyConstraint(["target_agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_relationships_target_agent_id_agents")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_relationships")),
        sa.UniqueConstraint("source_agent_id", "target_agent_id", name="uq_relationships_source_target"),
    )
    op.create_index("ix_relationships_source_agent_id", "relationships", ["source_agent_id"])
    op.create_index("ix_relationships_target_agent_id", "relationships", ["target_agent_id"])

    op.create_table(
        "pair_bonds",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_a_id", sa.Uuid(), nullable=False),
        sa.Column("agent_b_id", sa.Uuid(), nullable=False),
        sa.Column("state", pair_bond_state, nullable=False),
        sa.Column("bond_strength", sa.Float(), server_default="0", nullable=False),
        sa.Column("started_tick", sa.BigInteger(), nullable=False),
        sa.Column("ended_tick", sa.BigInteger(), nullable=True),
        sa.CheckConstraint("agent_a_id != agent_b_id", name=op.f("ck_pair_bonds_pair_bonds_distinct_agents")),
        sa.CheckConstraint("bond_strength >= 0", name=op.f("ck_pair_bonds_pair_bonds_bond_strength_non_negative")),
        sa.ForeignKeyConstraint(["agent_a_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_pair_bonds_agent_a_id_agents")),
        sa.ForeignKeyConstraint(["agent_b_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_pair_bonds_agent_b_id_agents")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pair_bonds")),
    )
    op.create_index("ix_pair_bonds_agent_a_id", "pair_bonds", ["agent_a_id"])
    op.create_index("ix_pair_bonds_agent_b_id", "pair_bonds", ["agent_b_id"])
    op.create_index("ix_pair_bonds_state", "pair_bonds", ["state"])

    op.create_table(
        "pregnancies",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("mother_id", sa.Uuid(), nullable=False),
        sa.Column("father_id", sa.Uuid(), nullable=True),
        sa.Column("started_tick", sa.BigInteger(), nullable=False),
        sa.Column("expected_birth_tick", sa.BigInteger(), nullable=False),
        sa.Column("status", pregnancy_status, nullable=False),
        sa.ForeignKeyConstraint(["father_id"], ["agents.id"], name=op.f("fk_pregnancies_father_id_agents")),
        sa.ForeignKeyConstraint(["mother_id"], ["agents.id"], name=op.f("fk_pregnancies_mother_id_agents")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pregnancies")),
    )
    op.create_index("ix_pregnancies_mother_id_status", "pregnancies", ["mother_id", "status"])
    op.create_index("ix_pregnancies_expected_birth_tick", "pregnancies", ["expected_birth_tick"])

    op.create_table(
        "agent_goals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("goal_type", goal_type, nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("priority", sa.Float(), nullable=False),
        sa.Column("horizon_days", sa.Integer(), nullable=False),
        sa.Column("status", goal_status, nullable=False),
        sa.Column("target_entity_type", sa.Text(), nullable=True),
        sa.Column("target_entity_id", sa.Uuid(), nullable=True),
        sa.Column("blocker_summary", sa.Text(), server_default="", nullable=False),
        sa.Column(
            "success_condition",
            postgresql.JSONB() if is_postgresql else sa.JSON(),
            server_default=sa.text("'{}'::jsonb") if is_postgresql else "{}",
            nullable=False,
        ),
        sa.Column("source", goal_source, nullable=False),
        sa.Column("created_tick", sa.BigInteger(), nullable=False),
        sa.Column("updated_tick", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("priority >= 0", name=op.f("ck_agent_goals_agent_goals_priority_non_negative")),
        sa.CheckConstraint("horizon_days >= 0", name=op.f("ck_agent_goals_agent_goals_horizon_days_non_negative")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_agent_goals_agent_id_agents")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_agent_goals")),
    )
    op.create_index("ix_agent_goals_agent_id_status", "agent_goals", ["agent_id", "status"])
    op.create_index("ix_agent_goals_created_tick", "agent_goals", ["created_tick"])

    op.create_table(
        "episodic_memories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("tick", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("location_x", sa.Integer(), nullable=True),
        sa.Column("location_y", sa.Integer(), nullable=True),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("valence", sa.Float(), nullable=False),
        sa.Column("salience", sa.Float(), nullable=False),
        sa.Column("participant_ids", UUIDArrayType(), server_default="[]", nullable=False),
        sa.Column("decay_rate", sa.Float(), server_default="0.01", nullable=False),
        sa.Column("archived", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.CheckConstraint("decay_rate >= 0", name=op.f("ck_episodic_memories_episodic_memories_decay_rate_non_negative")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_episodic_memories_agent_id_agents")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_episodic_memories")),
    )
    op.create_index("ix_episodic_memories_agent_id_tick", "episodic_memories", ["agent_id", "tick"])
    op.create_index("ix_episodic_memories_agent_id_archived_salience", "episodic_memories", ["agent_id", "archived", "salience"])

    op.create_table(
        "semantic_beliefs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("subject_type", sa.Text(), nullable=False),
        sa.Column("subject_id", sa.Uuid(), nullable=True),
        sa.Column("predicate", sa.Text(), nullable=False),
        sa.Column("object_value", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), server_default="1", nullable=False),
        sa.Column("last_supported_tick", sa.BigInteger(), nullable=False),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=op.f("ck_semantic_beliefs_semantic_beliefs_confidence_range")),
        sa.CheckConstraint("evidence_count >= 1", name=op.f("ck_semantic_beliefs_semantic_beliefs_evidence_count_positive")),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_semantic_beliefs_agent_id_agents")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_semantic_beliefs")),
    )
    op.create_index("ix_semantic_beliefs_agent_subject", "semantic_beliefs", ["agent_id", "subject_type", "subject_id"])

    op.create_table(
        "memory_embeddings",
        sa.Column("memory_id", sa.Uuid(), nullable=False),
        sa.Column("agent_id", sa.Uuid(), nullable=False),
        sa.Column("embedding", Vector1536(), nullable=False),
        sa.ForeignKeyConstraint(["agent_id"], ["agents.id"], ondelete="CASCADE", name=op.f("fk_memory_embeddings_agent_id_agents")),
        sa.ForeignKeyConstraint(["memory_id"], ["episodic_memories.id"], ondelete="CASCADE", name=op.f("fk_memory_embeddings_memory_id_episodic_memories")),
        sa.PrimaryKeyConstraint("memory_id", name=op.f("pk_memory_embeddings")),
    )
    op.create_index("ix_memory_embeddings_agent_id", "memory_embeddings", ["agent_id"])

    op.create_table(
        "world_events",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tick", sa.BigInteger(), nullable=False),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("actor_ids", UUIDArrayType(), server_default="[]", nullable=False),
        sa.Column("target_ids", UUIDArrayType(), server_default="[]", nullable=False),
        sa.Column("location_x", sa.Integer(), nullable=True),
        sa.Column("location_y", sa.Integer(), nullable=True),
        sa.Column(
            "payload",
            postgresql.JSONB() if is_postgresql else sa.JSON(),
            server_default=sa.text("'{}'::jsonb") if is_postgresql else "{}",
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_world_events")),
    )
    op.create_index("ix_world_events_tick", "world_events", ["tick"])
    op.create_index("ix_world_events_event_type", "world_events", ["event_type"])

    op.create_table(
        "inventories",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("owner_type", inventory_owner_type, nullable=False),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("item_type", sa.Text(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB() if is_postgresql else sa.JSON(),
            server_default=sa.text("'{}'::jsonb") if is_postgresql else "{}",
            nullable=False,
        ),
        sa.CheckConstraint("quantity >= 0", name=op.f("ck_inventories_inventories_quantity_non_negative")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventories")),
    )
    op.create_index("ix_inventories_owner", "inventories", ["owner_type", "owner_id"])
    op.create_index("ix_inventories_item_type", "inventories", ["item_type"])


def downgrade() -> None:
    op.drop_index("ix_inventories_item_type", table_name="inventories")
    op.drop_index("ix_inventories_owner", table_name="inventories")
    op.drop_table("inventories")

    op.drop_index("ix_world_events_event_type", table_name="world_events")
    op.drop_index("ix_world_events_tick", table_name="world_events")
    op.drop_table("world_events")

    op.drop_index("ix_memory_embeddings_agent_id", table_name="memory_embeddings")
    op.drop_table("memory_embeddings")

    op.drop_index("ix_semantic_beliefs_agent_subject", table_name="semantic_beliefs")
    op.drop_table("semantic_beliefs")

    op.drop_index("ix_episodic_memories_agent_id_archived_salience", table_name="episodic_memories")
    op.drop_index("ix_episodic_memories_agent_id_tick", table_name="episodic_memories")
    op.drop_table("episodic_memories")

    op.drop_index("ix_agent_goals_created_tick", table_name="agent_goals")
    op.drop_index("ix_agent_goals_agent_id_status", table_name="agent_goals")
    op.drop_table("agent_goals")

    op.drop_index("ix_pregnancies_expected_birth_tick", table_name="pregnancies")
    op.drop_index("ix_pregnancies_mother_id_status", table_name="pregnancies")
    op.drop_table("pregnancies")

    op.drop_index("ix_pair_bonds_state", table_name="pair_bonds")
    op.drop_index("ix_pair_bonds_agent_b_id", table_name="pair_bonds")
    op.drop_index("ix_pair_bonds_agent_a_id", table_name="pair_bonds")
    op.drop_table("pair_bonds")

    op.drop_index("ix_relationships_target_agent_id", table_name="relationships")
    op.drop_index("ix_relationships_source_agent_id", table_name="relationships")
    op.drop_table("relationships")

    op.drop_table("agent_skills")
    op.drop_table("agent_needs")
    op.drop_table("agent_traits")

    op.drop_index("ix_agents_home_building_id", table_name="agents")
    op.drop_index("ix_agents_household_id", table_name="agents")
    op.drop_index("ix_agents_alive", table_name="agents")
    op.drop_table("agents")
