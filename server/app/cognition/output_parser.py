"""Structured output parser stub for future reflection workflows."""

from __future__ import annotations

from app.schemas.reflection import ReflectionOutput, ReflectionResult


class ReflectionOutputParser:
    """Parse model outputs into structured reflection results."""

    def parse(self, output: ReflectionResult | ReflectionOutput) -> ReflectionResult:
        """Normalize reflection outputs into the legacy slow-loop result contract."""

        if isinstance(output, ReflectionResult):
            return output

        return output.to_reflection_result()
