"""Typed daily metrics and observability transport models."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class PopulationDailyMetrics(BaseModel):
    """Daily population metrics finalized from authoritative state and birth/death events."""

    model_config = ConfigDict(extra="forbid")

    total_population: int = Field(ge=0)
    births: int = Field(ge=0)
    deaths: int = Field(ge=0)
    infant_survival_rate: float | None = Field(default=None, ge=0.0, le=1.0)
    age_distribution: dict[str, int] = Field(default_factory=dict)


class WelfareDailyMetrics(BaseModel):
    """Daily welfare metrics derived from authoritative agent state."""

    model_config = ConfigDict(extra="forbid")

    average_hunger: float = Field(ge=0.0, le=100.0)
    average_thirst: float = Field(ge=0.0, le=100.0)
    average_stress: float = Field(ge=0.0, le=100.0)
    starvation_count: int = Field(ge=0)
    illness_count: int | None = Field(default=None, ge=0)


class SocialDailyMetrics(BaseModel):
    """Daily social metrics from authoritative state and domain events."""

    model_config = ConfigDict(extra="forbid")

    active_bonds: int = Field(ge=0)
    household_count: int = Field(ge=0)
    mean_trust: float | None = Field(default=None, ge=0.0, le=1.0)
    conflict_events: int = Field(ge=0)
    gifts_per_day: int = Field(ge=0)


class EconomyDailyMetrics(BaseModel):
    """Daily economy metrics from inventories, stocks, and successful work tasks."""

    model_config = ConfigDict(extra="forbid")

    food_reserves: int = Field(ge=0)
    water_reserves: int = Field(ge=0)
    crop_yield: int = Field(ge=0)
    wood_stock: int = Field(ge=0)
    cooked_meals_per_day: int = Field(ge=0)


class CognitionDailyMetrics(BaseModel):
    """Daily cognition metrics from slow-loop and reflection observability hooks."""

    model_config = ConfigDict(extra="forbid")

    reflections_per_day: int = Field(ge=0)
    average_memories_retrieved: float | None = Field(default=None, ge=0.0)
    invalid_model_outputs: int = Field(ge=0)
    mean_token_cost_per_day: float | None = Field(default=None, ge=0.0)


class DailyMetricsSnapshot(BaseModel):
    """One finalized day of authoritative observability metrics."""

    model_config = ConfigDict(extra="forbid")

    day_index: int = Field(ge=0)
    finalized_at: datetime
    population: PopulationDailyMetrics
    welfare: WelfareDailyMetrics
    social: SocialDailyMetrics
    economy: EconomyDailyMetrics
    cognition: CognitionDailyMetrics
