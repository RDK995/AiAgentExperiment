"""Deterministic trait inheritance helpers for newborn agents."""

from __future__ import annotations

from collections.abc import Callable


def clamp_unit(value: float) -> float:
    """Clamp one trait value to the supported [0, 1] range."""

    return max(0.0, min(1.0, value))


class TraitInheritanceService:
    """Generate compact inherited trait bundles from parent values."""

    _SUPPORTED_TRAITS = (
        "sociability",
        "aggression",
        "conscientiousness",
        "curiosity",
        "family_orientation",
        "risk_tolerance",
        "libido",
        "emotional_stability",
        "memory_fidelity",
        "learning_rate",
    )

    def __init__(self, *, variation_fn: Callable[[str], float] | None = None) -> None:
        self._variation_fn = variation_fn or (lambda _trait_name: 0.0)

    def inherit_runtime_family_orientation(self, parent_a: float, parent_b: float) -> float:
        """Return the runtime family-orientation value for a newborn child."""

        return clamp_unit(((parent_a + parent_b) / 2.0) + self._variation_fn("family_orientation"))

    def inherit_persistent_traits(
        self,
        parent_a_traits: dict[str, float] | None,
        parent_b_traits: dict[str, float] | None,
    ) -> dict[str, float]:
        """Build a full persistent trait bundle from parent trait dictionaries."""

        parent_a_traits = parent_a_traits or {}
        parent_b_traits = parent_b_traits or {}
        inherited: dict[str, float] = {}
        for trait_name in self._SUPPORTED_TRAITS:
            parent_a_value = parent_a_traits.get(trait_name, 0.5)
            parent_b_value = parent_b_traits.get(trait_name, 0.5)
            inherited[trait_name] = clamp_unit(
                ((parent_a_value + parent_b_value) / 2.0) + self._variation_fn(trait_name)
            )
        return inherited
