"""Daily metrics aggregation for authoritative simulation observability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select

from app.db.models import Relationship
from app.engine.world_state import AgentState, WorldState
from app.schemas.event import EventType, SimulationEvent
from app.schemas.metrics import (
    CognitionDailyMetrics,
    DailyMetricsSnapshot,
    EconomyDailyMetrics,
    PopulationDailyMetrics,
    SocialDailyMetrics,
    WelfareDailyMetrics,
)

if TYPE_CHECKING:
    from app.cognition.slow_loop import SlowLoopResult


_FOOD_ITEM_TYPES = {"meal", "food", "berries", "fruit", "fish", "crop"}
_WATER_ITEM_TYPES = {"water"}
_WOOD_ITEM_TYPES = {"wood"}


@dataclass(slots=True)
class _DailyCounters:
    """Mutable per-day counters fed by events and slow-loop instrumentation."""

    births: int = 0
    deaths: int = 0
    conflict_events: int = 0
    gifts_per_day: int = 0
    crop_yield: int = 0
    cooked_meals_per_day: int = 0
    reflections_per_day: int = 0
    invalid_model_outputs: int = 0
    total_memories_retrieved: int = 0
    total_token_cost: float = 0.0
    newborn_ids: set[str] = field(default_factory=set)


class DailyMetricsCollector:
    """Collect daily observability metrics from authoritative state and events.

    Definitions used here are explicit and intentionally compact:
    - infant survival rate:
      proportion of agents born during the finalized day that are still alive and
      still in the infant stage at finalization time. Returns ``None`` on days
      with no births.
    - starvation count:
      alive agents with hunger >= 90.0 at end-of-day finalization.
    - illness count:
      currently unavailable in runtime state, so reported as ``None``.
    - mean trust:
      arithmetic mean of persisted directed relationship rows when persistence is
      configured. Returns ``None`` when no relationship store is available.
    - token cost:
      current reflection path uses a deterministic stubbed model client, so this
      remains 0.0 per reflection until real usage accounting exists.
    """

    def __init__(
        self,
        *,
        session_scope=None,
        history_limit: int = 30,
    ) -> None:
        self._session_scope = session_scope
        self._history_limit = history_limit
        self._current_day_index: int | None = None
        self._current = _DailyCounters()
        self._history: list[DailyMetricsSnapshot] = []

    def start_day(self, day_index: int) -> None:
        """Initialize the collector for the active simulation day."""

        if self._current_day_index is None:
            self._current_day_index = day_index

    def observe_event(self, event: SimulationEvent) -> None:
        """Count day-scoped domain events as they flow through the authoritative bus."""

        if self._current_day_index is None:
            self._current_day_index = event.sim_time.toordinal()

        if event.type is EventType.CHILD_BORN:
            self._current.births += 1
            self._current.newborn_ids.update(event.target_ids)
        elif event.type is EventType.AGENT_DIED:
            self._current.deaths += 1
        elif event.type is EventType.GIFT_GIVEN:
            self._current.gifts_per_day += 1
        elif event.type is EventType.INSULT_SPOKEN:
            self._current.conflict_events += 1
        elif event.type is EventType.TASK_COMPLETED:
            task_name = str(event.payload.get("task", ""))
            if task_name == "cook_food":
                self._current.cooked_meals_per_day += 1
            elif task_name == "harvest_crop":
                self._current.crop_yield += 1

    def observe_reflection_results(self, day_index: int, results: list["SlowLoopResult"]) -> None:
        """Accumulate daily cognition metrics from the shared slow-loop service."""

        if self._current_day_index is None:
            self._current_day_index = day_index
        if self._current_day_index != day_index:
            return

        for result in results:
            self._current.reflections_per_day += 1
            self._current.total_memories_retrieved += result.retrieved_memory_count
            self._current.total_token_cost += result.token_cost
            if result.failure_stage in {"parse_json", "validate"}:
                self._current.invalid_model_outputs += 1

    def finalize_day(
        self,
        world: WorldState,
        *,
        day_index: int,
        finalized_at: datetime,
        next_day_index: int | None = None,
    ) -> DailyMetricsSnapshot:
        """Finalize the current day using authoritative world state and reset counters."""

        if self._current_day_index is None:
            self._current_day_index = day_index

        snapshot = DailyMetricsSnapshot(
            day_index=day_index,
            finalized_at=finalized_at,
            population=self._build_population_metrics(world),
            welfare=self._build_welfare_metrics(world),
            social=self._build_social_metrics(world),
            economy=self._build_economy_metrics(world),
            cognition=self._build_cognition_metrics(),
        )
        self._history.append(snapshot)
        self._history = self._history[-self._history_limit :]
        self._current = _DailyCounters()
        self._current_day_index = next_day_index
        return snapshot

    def latest_snapshot(self) -> DailyMetricsSnapshot | None:
        """Return the most recent finalized day of metrics."""

        if not self._history:
            return None
        return self._history[-1]

    def current_snapshot(self, world: WorldState, *, finalized_at: datetime) -> DailyMetricsSnapshot | None:
        """Return an in-progress view of the active day's metrics for debug surfaces.

        This does not mutate history or counters. It exists so dashboards can show
        authoritative observability before the first end-of-day rollover.
        """

        if self._current_day_index is None:
            return None
        return DailyMetricsSnapshot(
            day_index=self._current_day_index,
            finalized_at=finalized_at,
            population=self._build_population_metrics(world),
            welfare=self._build_welfare_metrics(world),
            social=self._build_social_metrics(world),
            economy=self._build_economy_metrics(world),
            cognition=self._build_cognition_metrics(),
        )

    def recent_snapshots(self, limit: int = 7) -> list[DailyMetricsSnapshot]:
        """Return a bounded recent history of finalized daily metrics."""

        return list(self._history[-limit:])

    def _build_population_metrics(self, world: WorldState) -> PopulationDailyMetrics:
        alive_agents = [agent for agent in world.agents if agent.alive]
        age_distribution: dict[str, int] = {}
        for agent in alive_agents:
            key = agent.stage_of_life.value
            age_distribution[key] = age_distribution.get(key, 0) + 1

        infant_survival_rate: float | None = None
        if self._current.births > 0:
            surviving_newborns = sum(
                1
                for agent in alive_agents
                if agent.agent_id in self._current.newborn_ids and agent.stage_of_life.value == "infant"
            )
            infant_survival_rate = round(surviving_newborns / self._current.births, 4)

        return PopulationDailyMetrics(
            total_population=len(alive_agents),
            births=self._current.births,
            deaths=self._current.deaths,
            infant_survival_rate=infant_survival_rate,
            age_distribution=age_distribution,
        )

    def _build_welfare_metrics(self, world: WorldState) -> WelfareDailyMetrics:
        alive_agents = [agent for agent in world.agents if agent.alive]
        if not alive_agents:
            return WelfareDailyMetrics(
                average_hunger=0.0,
                average_thirst=0.0,
                average_stress=0.0,
                starvation_count=0,
                illness_count=None,
            )

        agent_count = float(len(alive_agents))
        average_hunger = round(sum(agent.hunger for agent in alive_agents) / agent_count, 4)
        average_thirst = round(sum(agent.thirst for agent in alive_agents) / agent_count, 4)
        average_stress = round(sum(agent.stress for agent in alive_agents) / agent_count, 4)
        starvation_count = sum(1 for agent in alive_agents if agent.hunger >= 90.0)
        return WelfareDailyMetrics(
            average_hunger=average_hunger,
            average_thirst=average_thirst,
            average_stress=average_stress,
            starvation_count=starvation_count,
            illness_count=None,
        )

    def _build_social_metrics(self, world: WorldState) -> SocialDailyMetrics:
        alive_agents = [agent for agent in world.agents if agent.alive]
        active_pairs: set[tuple[str, str]] = set()
        for agent in alive_agents:
            if agent.partner_id is None:
                continue
            partner = world.agent_by_id(agent.partner_id)
            if partner is None or not partner.alive or partner.partner_id != agent.agent_id:
                continue
            active_pairs.add(tuple(sorted((agent.agent_id, partner.agent_id))))

        household_count = len({agent.household_id for agent in alive_agents if agent.household_id is not None})
        return SocialDailyMetrics(
            active_bonds=len(active_pairs),
            household_count=household_count,
            mean_trust=self._compute_mean_trust(),
            conflict_events=self._current.conflict_events,
            gifts_per_day=self._current.gifts_per_day,
        )

    def _build_economy_metrics(self, world: WorldState) -> EconomyDailyMetrics:
        return EconomyDailyMetrics(
            food_reserves=self._sum_reserves(world, _FOOD_ITEM_TYPES),
            water_reserves=self._sum_reserves(world, _WATER_ITEM_TYPES),
            crop_yield=self._current.crop_yield,
            wood_stock=self._sum_reserves(world, _WOOD_ITEM_TYPES),
            cooked_meals_per_day=self._current.cooked_meals_per_day,
        )

    def _build_cognition_metrics(self) -> CognitionDailyMetrics:
        reflections = self._current.reflections_per_day
        average_memories = None
        mean_token_cost = None
        if reflections > 0:
            average_memories = round(self._current.total_memories_retrieved / reflections, 4)
            mean_token_cost = round(self._current.total_token_cost / reflections, 6)
        return CognitionDailyMetrics(
            reflections_per_day=reflections,
            average_memories_retrieved=average_memories,
            invalid_model_outputs=self._current.invalid_model_outputs,
            mean_token_cost_per_day=mean_token_cost,
        )

    def _sum_reserves(self, world: WorldState, item_types: set[str]) -> int:
        total = 0
        for agent in world.agents:
            total += self._sum_inventory(agent.inventory, item_types)
            total += self._sum_inventory(agent.home_inventory, item_types)
        total += sum(
            item.quantity
            for item in world.items
            if item.item_type in item_types
        )
        return total

    @staticmethod
    def _sum_inventory(inventory: dict[str, int], item_types: set[str]) -> int:
        return sum(quantity for item_type, quantity in inventory.items() if item_type in item_types)

    def _compute_mean_trust(self) -> float | None:
        if self._session_scope is None:
            return None
        with self._session_scope() as session:
            trust_values = list(session.scalars(select(Relationship.trust)))
        if not trust_values:
            return None
        return round(sum(float(value) for value in trust_values) / len(trust_values), 4)
