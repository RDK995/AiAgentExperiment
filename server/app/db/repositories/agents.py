"""Repository helpers for persistent agent records and related graphs."""

from __future__ import annotations

from dataclasses import dataclass, field
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.db.enums import AgentSex, GoalSource, GoalStatus, GoalType, KinshipType, StageOfLife
from app.db.models import Agent, AgentGoal, AgentNeed, AgentSkill, AgentTrait, Relationship


@dataclass(slots=True)
class AgentCreateParams:
    """Parameters for creating an agent plus required one-to-one records."""

    name: str
    sex: AgentSex
    birth_tick: int
    current_tile_x: int
    current_tile_y: int
    stage_of_life: StageOfLife
    biography_summary: str = ""
    trait_values: dict[str, float] = field(default_factory=dict)
    need_values: dict[str, float] = field(default_factory=dict)
    skill_values: dict[str, float] = field(default_factory=dict)


@dataclass(slots=True)
class RelationshipCreateParams:
    """Parameters for creating a directed relationship between two agents."""

    source_agent_id: uuid.UUID
    target_agent_id: uuid.UUID
    familiarity: float = 0.0
    trust: float = 0.0
    attraction: float = 0.0
    resentment: float = 0.0
    admiration: float = 0.0
    fear: float = 0.0
    obligation: float = 0.0
    dependency: float = 0.0
    kinship_type: KinshipType | None = None
    last_interaction_tick: int | None = None


@dataclass(slots=True)
class GoalCreateParams:
    """Parameters for creating a persistent goal record."""

    agent_id: uuid.UUID
    goal_type: GoalType
    title: str
    priority: float
    horizon_days: int
    status: GoalStatus
    source: GoalSource
    created_tick: int
    updated_tick: int
    target_entity_type: str | None = None
    target_entity_id: uuid.UUID | None = None
    blocker_summary: str = ""
    success_condition: dict[str, object] = field(default_factory=dict)


@dataclass(slots=True)
class GoalUpdateParams:
    """Optional fields for updating an existing goal record."""

    title: str | None = None
    priority: float | None = None
    horizon_days: int | None = None
    status: GoalStatus | None = None
    blocker_summary: str | None = None
    success_condition: dict[str, object] | None = None
    updated_tick: int | None = None


class AgentRepository:
    """Persistence helper for agent graphs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create_agent_bundle(self, params: AgentCreateParams) -> Agent:
        """Create an agent with required one-to-one state rows."""

        agent = Agent(
            name=params.name,
            sex=params.sex,
            birth_tick=params.birth_tick,
            current_tile_x=params.current_tile_x,
            current_tile_y=params.current_tile_y,
            stage_of_life=params.stage_of_life,
            biography_summary=params.biography_summary,
        )
        agent.traits = AgentTrait(
            sociability=params.trait_values.get("sociability", 0.5),
            aggression=params.trait_values.get("aggression", 0.2),
            conscientiousness=params.trait_values.get("conscientiousness", 0.5),
            curiosity=params.trait_values.get("curiosity", 0.5),
            family_orientation=params.trait_values.get("family_orientation", 0.5),
            risk_tolerance=params.trait_values.get("risk_tolerance", 0.3),
            libido=params.trait_values.get("libido", 0.5),
            emotional_stability=params.trait_values.get("emotional_stability", 0.7),
            memory_fidelity=params.trait_values.get("memory_fidelity", 0.7),
            learning_rate=params.trait_values.get("learning_rate", 0.6),
        )
        agent.needs = AgentNeed(
            hunger=params.need_values.get("hunger", 0.0),
            thirst=params.need_values.get("thirst", 0.0),
            fatigue=params.need_values.get("fatigue", 0.0),
            warmth=params.need_values.get("warmth", 100.0),
            health=params.need_values.get("health", 100.0),
            stress=params.need_values.get("stress", 0.0),
            loneliness=params.need_values.get("loneliness", 0.0),
            safety=params.need_values.get("safety", 100.0),
        )
        agent.skills = AgentSkill(
            farming=params.skill_values.get("farming", 0.0),
            fishing=params.skill_values.get("fishing", 0.0),
            gathering=params.skill_values.get("gathering", 0.0),
            cooking=params.skill_values.get("cooking", 0.0),
            crafting=params.skill_values.get("crafting", 0.0),
            caregiving=params.skill_values.get("caregiving", 0.0),
            social=params.skill_values.get("social", 0.0),
        )
        self._session.add(agent)
        self._session.flush()
        return agent

    def get_agent_with_related(self, agent_id) -> Agent | None:
        """Fetch an agent with high-value related records eagerly loaded."""

        statement = (
            select(Agent)
            .where(Agent.id == agent_id)
            .options(
                joinedload(Agent.traits),
                joinedload(Agent.needs),
                joinedload(Agent.skills),
                joinedload(Agent.goals),
            )
        )
        return self._session.scalar(statement)

    def list_alive_agents(self) -> list[Agent]:
        """Return all currently alive agents."""

        return list(self._session.scalars(select(Agent).where(Agent.alive.is_(True)).order_by(Agent.name)))

    def add_goal(self, goal: AgentGoal) -> AgentGoal:
        """Persist a goal record."""

        self._session.add(goal)
        self._session.flush()
        return goal

    def add_relationship(self, relationship: Relationship) -> Relationship:
        """Persist a relationship record."""

        self._session.add(relationship)
        self._session.flush()
        return relationship

    def create_relationship(self, params: RelationshipCreateParams) -> Relationship:
        """Create and persist a directed relationship record."""

        relationship = Relationship(
            source_agent_id=params.source_agent_id,
            target_agent_id=params.target_agent_id,
            familiarity=params.familiarity,
            trust=params.trust,
            attraction=params.attraction,
            resentment=params.resentment,
            admiration=params.admiration,
            fear=params.fear,
            obligation=params.obligation,
            dependency=params.dependency,
            kinship_type=params.kinship_type,
            last_interaction_tick=params.last_interaction_tick,
        )
        return self.add_relationship(relationship)

    def get_relationship(self, source_agent_id: uuid.UUID, target_agent_id: uuid.UUID) -> Relationship | None:
        """Fetch a relationship by its directed source and target agent IDs."""

        statement = select(Relationship).where(
            Relationship.source_agent_id == source_agent_id,
            Relationship.target_agent_id == target_agent_id,
        )
        return self._session.scalar(statement)

    def list_relationships_for_agent(self, agent_id: uuid.UUID) -> list[Relationship]:
        """Return directed relationships where the agent is either source or target."""

        statement = (
            select(Relationship)
            .where(
                (Relationship.source_agent_id == agent_id)
                | (Relationship.target_agent_id == agent_id)
            )
            .order_by(Relationship.last_interaction_tick.desc(), Relationship.id)
        )
        return list(self._session.scalars(statement))

    def create_goal(self, params: GoalCreateParams) -> AgentGoal:
        """Create and persist a goal record."""

        goal = AgentGoal(
            agent_id=params.agent_id,
            goal_type=params.goal_type,
            title=params.title,
            priority=params.priority,
            horizon_days=params.horizon_days,
            status=params.status,
            target_entity_type=params.target_entity_type,
            target_entity_id=params.target_entity_id,
            blocker_summary=params.blocker_summary,
            success_condition=params.success_condition,
            source=params.source,
            created_tick=params.created_tick,
            updated_tick=params.updated_tick,
        )
        return self.add_goal(goal)

    def get_goal(self, goal_id: uuid.UUID) -> AgentGoal | None:
        """Fetch a goal by primary key."""

        return self._session.get(AgentGoal, goal_id)

    def list_goals_for_agent(
        self,
        agent_id: uuid.UUID,
        *,
        status: GoalStatus | None = None,
    ) -> list[AgentGoal]:
        """List goals for an agent, optionally filtering by status."""

        statement = select(AgentGoal).where(AgentGoal.agent_id == agent_id)
        if status is not None:
            statement = statement.where(AgentGoal.status == status)
        statement = statement.order_by(AgentGoal.priority.desc(), AgentGoal.created_tick, AgentGoal.id)
        return list(self._session.scalars(statement))

    def update_goal(self, goal_id: uuid.UUID, params: GoalUpdateParams) -> AgentGoal:
        """Update a goal in place and flush the changes."""

        goal = self._session.get(AgentGoal, goal_id)
        if goal is None:
            raise LookupError(f"Unknown goal '{goal_id}'.")

        if params.title is not None:
            goal.title = params.title
        if params.priority is not None:
            goal.priority = params.priority
        if params.horizon_days is not None:
            goal.horizon_days = params.horizon_days
        if params.status is not None:
            goal.status = params.status
        if params.blocker_summary is not None:
            goal.blocker_summary = params.blocker_summary
        if params.success_condition is not None:
            goal.success_condition = params.success_condition
        if params.updated_tick is not None:
            goal.updated_tick = params.updated_tick

        self._session.flush()
        return goal
