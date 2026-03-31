"""Physiological need updates for the agent fast loop."""

from __future__ import annotations

from app.engine.world_state import AgentState


class NeedService:
    """Applies deterministic physiological need decay."""

    def update(self, agent: AgentState) -> None:
        """Advance the agent's physiological needs by one fast-loop step."""

        agent.advance_needs()
