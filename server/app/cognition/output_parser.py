"""Structured output parser stub for future reflection workflows."""

from __future__ import annotations

from app.schemas.reflection import ReflectionResult


class ReflectionOutputParser:
    """Parse model outputs into structured reflection results."""

    def parse(self, output: ReflectionResult) -> ReflectionResult:
        """The prototype workflow already returns structured outputs."""

        return output
