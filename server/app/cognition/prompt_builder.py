"""Deterministic reflection prompt builder stub."""

from __future__ import annotations

from app.schemas.reflection import ReflectionContext


class ReflectionPromptBuilder:
    """Build a deterministic compact prompt description from reflection context."""

    def build(self, context: ReflectionContext) -> str:
        """Return a compact textual prompt stub for future model integration."""

        return (
            f"Agent {context.agent_id}; triggers={','.join(context.trigger_reasons)}; "
            f"autobiography={context.autobiography}"
        )
