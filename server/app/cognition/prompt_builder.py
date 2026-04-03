"""Deterministic reflection prompt builder stub."""

from __future__ import annotations

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
