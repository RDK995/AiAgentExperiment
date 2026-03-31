"""Helpers for building compact autobiography slices for reflection."""

from __future__ import annotations

from app.engine.world_state import AgentState


class AutobiographyBuilder:
    """Build a compact deterministic autobiography summary for an agent."""

    def build(self, agent: AgentState, recent_events: list[str]) -> str:
        """Summarize current state and recent events into a compact slice."""

        event_text = "; ".join(recent_events[-3:]) if recent_events else "No notable events."
        return (
            f"{agent.name} is feeling {agent.mood} and pursuing '{agent.current_goal}'. "
            f"Recent events: {event_text}"
        )
