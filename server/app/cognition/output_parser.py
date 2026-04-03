"""Structured output parser stub for future reflection workflows."""

from __future__ import annotations

import json

from app.schemas.reflection import ReflectionOutput, ReflectionResult


class ReflectionParseError(ValueError):
    """Raised when model output cannot be parsed into structured reflection JSON."""


class ReflectionOutputParser:
    """Parse model outputs into structured reflection results."""

    def parse(self, output: ReflectionResult | ReflectionOutput | str) -> ReflectionResult:
        """Normalize reflection outputs into the legacy slow-loop result contract."""

        if isinstance(output, ReflectionResult):
            return output

        if isinstance(output, str):
            structured = self.parse_output(output)
            return structured.to_reflection_result()

        return output.to_reflection_result()

    def parse_output(self, output: ReflectionOutput | str) -> ReflectionOutput:
        """Parse model JSON into the structured reflection output DTO."""

        if isinstance(output, ReflectionOutput):
            return output

        try:
            payload = json.loads(output)
        except json.JSONDecodeError as exc:
            raise ReflectionParseError("Malformed reflection JSON output.") from exc

        try:
            return ReflectionOutput.model_validate(payload)
        except Exception as exc:  # pragma: no cover - pydantic error specifics are not important here
            raise ReflectionParseError("Reflection JSON failed schema validation.") from exc
