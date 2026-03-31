"""Deterministic perception service for the agent fast loop."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.engine.world_state import AgentState, WorldState


@dataclass(slots=True)
class PerceivedContext:
    """Local agent context used by fast-loop scoring."""

    sim_time: datetime
    weather: str
    nearby_agent_count: int
    terrain: str
    hunger: float
    thirst: float
    fatigue: float


class PerceptionService:
    """Build a compact local view of the authoritative world for an agent."""

    def perceive(self, world: WorldState, agent: AgentState, now: datetime) -> PerceivedContext:
        nearby_agent_count = sum(
            1
            for other in world.agents
            if other.agent_id != agent.agent_id
            and abs(other.x - agent.x) + abs(other.y - agent.y) <= 2
        )
        terrain = world.terrain_at(agent.x, agent.y)
        return PerceivedContext(
            sim_time=now,
            weather=world.weather,
            nearby_agent_count=nearby_agent_count,
            terrain=terrain,
            hunger=agent.hunger,
            thirst=agent.thirst,
            fatigue=agent.fatigue,
        )
