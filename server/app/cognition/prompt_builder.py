"""Deterministic reflection prompt builder stub."""

from __future__ import annotations

from app.engine.world_state import AgentState
from app.schemas.reflection import ReflectionContext


class ReflectionPromptBuilder:
    """Build a deterministic compact prompt description from reflection context."""

    def build(self, context: ReflectionContext) -> str:
        """Return a compact textual prompt stub for future model integration."""

        goals = ",".join(context.goals[:3]) if context.goals else "none"
        relationships = ",".join(context.relationships[:3]) if context.relationships else "none"
        recent_events = "; ".join(context.recent_events[:3]) if context.recent_events else "none"
        return (
            f"Agent {context.agent_id}; triggers={','.join(context.trigger_reasons)}; "
            f"autobiography={context.autobiography}; "
            f"goals={goals}; relationships={relationships}; recent_events={recent_events}"
        )

    def build_for_agent(self, agent: AgentState, context: ReflectionContext) -> str:
        """Return a compact deterministic prompt using agent state and retrieval context."""

        needs = (
            f"hunger={agent.hunger:.1f}, thirst={agent.thirst:.1f}, fatigue={agent.fatigue:.1f}, "
            f"health={agent.health:.1f}, stress={agent.stress:.1f}, morale={agent.morale:.1f}"
        )
        goals = ", ".join(context.goals[:3]) if context.goals else "none"
        relationships = ", ".join(context.relationships[:5]) if context.relationships else "none"
        memories = " | ".join(context.recent_events[:5]) if context.recent_events else "none"
        return (
            "You are generating structured internal reflection for one villager in a simulation.\n\n"
            "Rules:\n"
            "- Do not invent impossible world facts.\n"
            "- Only use provided state and memories.\n"
            "- Keep priorities between 0 and 1.\n"
            "- Output valid JSON only.\n\n"
            f"Agent:\n{agent.name}, {agent.stage_of_life.value}\n\n"
            f"Current needs:\n{needs}\n\n"
            f"Current goals:\n{goals}\n\n"
            f"Important relationships:\n{relationships}\n\n"
            f"Relevant memories:\n{memories}\n\n"
            f"Autobiographical summary:\n{context.autobiography}\n\n"
            "Task:\nUpdate beliefs, emotional shifts, and priorities for tomorrow."
        )
