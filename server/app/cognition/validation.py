"""Validation for structured reflection outputs before state mutation."""

from __future__ import annotations

from app.schemas.reflection import ReflectionResult


class ReflectionValidationError(ValueError):
    """Raised when reflection outputs fail validation."""


class ReflectionValidator:
    """Validate reflection outputs before applying them to agent state."""

    def validate(self, result: ReflectionResult) -> ReflectionResult:
        """Ensure outputs are structured, bounded, and non-empty."""

        for field_name in ("goals", "beliefs", "memory_entries", "planner_hints"):
            values = getattr(result, field_name)
            if not values:
                raise ReflectionValidationError(f"{field_name} must contain at least one entry.")
            if len(values) > 5:
                raise ReflectionValidationError(f"{field_name} exceeded maximum length.")
            if any(not value.strip() for value in values):
                raise ReflectionValidationError(f"{field_name} contains empty entries.")

        return result
