"""Simulation runtime and tick-loop orchestration."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import timedelta
import uuid

from sqlalchemy.orm import Session

from app.agents.executor import ActionExecutor
from app.agents.lifecycle import LifecycleService
from app.agents.needs import NeedService
from app.agents.perception import PerceptionService
from app.agents.planner import ActionPlanner
from app.agents.runtime import AgentRuntime
from app.agents.utility_ai import UtilityAI
from app.cognition.belief_updater import BeliefUpdater
from app.cognition.goal_updater import GoalUpdater
from app.cognition.reflection import ReflectionWorkflow
from app.cognition.reflection_graph import AutobiographyBuilder
from app.cognition.slow_loop import SlowLoopService
from app.cognition.validation import ReflectionValidator
from app.engine.event_bus import EventBus
from app.engine.event_listeners import (
    RelationshipEventListener,
    ReplayEventLog,
    WorldEventPersistenceListener,
)
from app.engine.rules.simulation_rules import is_action_legal
from app.engine.scheduler import TaskScheduler
from app.engine.sim_clock import SimulationClock
from app.engine.world_loop import WorldLoop
from app.engine.world_state import AgentState, ItemStackState, WorldState, build_initial_world_state
from app.memory.embeddings import EmbeddingProvider
from app.memory.retriever import MemoryRetriever
from app.memory.pipeline import MemoryPipelineListener
from app.memory.writer import MemoryWriter
from app.schemas.api import (
    AdvanceDaysResponse,
    AgentInspectResponse,
    BeliefsResponse,
    BeliefSummary,
    ChunkResponse,
    DailySummaryCandidateSummary,
    DailySummaryCandidatesResponse,
    DebugMetricsResponse,
    EpisodesResponse,
    ForceReflectResponse,
    GoalsResponse,
    GoalSummary,
    HouseholdInspectResponse,
    MemoryEpisodeSummary,
    MemoryRetrieveResponse,
    MemorySummarizeResponse,
    RelationshipsResponse,
    RelationshipSummary,
    ReplayResponse,
    ReplayEventResponse,
    ResetWorldResponse,
    SimulationSnapshot,
    SpawnFoodResponse,
    TimelineEntry,
    TimelineResponse,
)
from app.schemas.agent import AgentStateSnapshot
from app.schemas.event import EventType, SimulationEvent, WorldEventSchema
from app.telemetry.metrics import TelemetryRecorder


class SimulationRuntime:
    """Owns the authoritative world state and advances it over time."""

    def __init__(
        self,
        initial_state: WorldState,
        tick_interval_seconds: float,
        *,
        world_event_session_scope: Callable[[], AbstractContextManager[Session]] | None = None,
        persistent_agent_id_resolver: Callable[[str], uuid.UUID | None] | None = None,
        memory_embedding_provider: EmbeddingProvider | None = None,
    ) -> None:
        self._world_state = initial_state
        self._tick_interval_seconds = tick_interval_seconds
        self._world_event_session_scope = world_event_session_scope
        self._persistent_agent_id_resolver = persistent_agent_id_resolver
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._running = False
        self._scheduler = TaskScheduler()
        self._telemetry = TelemetryRecorder()
        self._replay_log = ReplayEventLog(max_events=200)
        self._recent_events: list[SimulationEvent] = []
        self._memory_retriever = MemoryRetriever()
        self._memory_embedding_provider = memory_embedding_provider
        self._event_bus = self._build_event_bus()
        self._sim_clock = SimulationClock(
            start_time=initial_state.current_time,
            tick_interval=timedelta(seconds=tick_interval_seconds),
        )
        self._slow_loop_service = SlowLoopService(
            memory_retriever=self._memory_retriever,
            autobiography_builder=AutobiographyBuilder(),
            reflection_workflow=ReflectionWorkflow(),
            validator=ReflectionValidator(),
            goal_updater=GoalUpdater(),
            belief_updater=BeliefUpdater(),
            memory_writer=MemoryWriter(),
        )
        self._agent_runtime = AgentRuntime(
            perception_service=PerceptionService(),
            need_service=NeedService(),
            utility_ai=UtilityAI(),
            planner=ActionPlanner(),
            executor=ActionExecutor(),
            slow_loop_service=self._slow_loop_service,
            lifecycle_service=LifecycleService(),
        )
        self._world_loop = WorldLoop(
            world_state=self._world_state,
            sim_clock=self._sim_clock,
            scheduler=self._scheduler,
            agent_runtime=self._agent_runtime,
            telemetry=self._telemetry,
            event_bus=self._event_bus,
        )

    async def start(self) -> None:
        """Start the background tick loop if it is not already running."""

        if self._running:
            return
        self._running = True
        self._task = asyncio.create_task(self._run_loop(), name="simulation-tick-loop")

    async def stop(self) -> None:
        """Stop the background tick loop and wait for shutdown."""

        self._running = False
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run_loop(self) -> None:
        """Advance the simulation on a fixed interval."""

        while self._running:
            await asyncio.sleep(self._tick_interval_seconds)
            await self.step_once()

    async def step_once(self) -> SimulationSnapshot:
        """Advance the authoritative state by one tick and return the snapshot."""

        async with self._lock:
            return self._step_once_locked()

    async def get_snapshot(self) -> SimulationSnapshot:
        """Return a consistent snapshot of current authoritative state."""

        async with self._lock:
            return self._world_state.to_snapshot()

    async def get_agent_snapshots(self) -> list[AgentStateSnapshot]:
        """Return richer backend-facing snapshots for all authoritative agents."""

        async with self._lock:
            return [agent.to_state_snapshot() for agent in self._world_state.agents]

    async def get_agent_snapshot(self, agent_id: str) -> AgentStateSnapshot:
        """Return a richer backend-facing snapshot for one authoritative agent."""

        async with self._lock:
            agent = self._get_agent(agent_id)
            if agent is None:
                raise LookupError(f"Unknown agent '{agent_id}'.")
            return agent.to_state_snapshot()

    async def run_for_ticks(self, ticks: int) -> SimulationSnapshot:
        """Advance the simulation by a fixed number of authoritative ticks."""

        async with self._lock:
            latest_snapshot: SimulationSnapshot | None = None
            for _ in range(ticks):
                latest_snapshot = self._step_once_locked()
            assert latest_snapshot is not None
            return latest_snapshot

    async def move_agent(self, agent_id: str, target_x: int, target_y: int) -> SimulationSnapshot:
        """Apply an authoritative movement action if it is legal."""

        async with self._lock:
            agent = self._get_agent(agent_id)
            if agent is None:
                raise LookupError(f"Unknown agent '{agent_id}'.")

            if not is_action_legal(
                self._world_state,
                agent,
                action="move",
                target_x=target_x,
                target_y=target_y,
            ):
                raise ValueError("Illegal move for current world state.")

            agent.x = target_x
            agent.y = target_y
            agent.current_action = "walking"
            return self._world_state.to_snapshot()

    async def get_world_chunk(self, anchor_x: int, anchor_y: int, size: int = 4) -> ChunkResponse:
        """Return a deterministic square chunk anchored at a world tile."""

        async with self._lock:
            if anchor_x >= self._world_state.width or anchor_y >= self._world_state.height:
                raise ValueError("Chunk coordinates must fall within world bounds.")
            max_x = min(self._world_state.width, anchor_x + size)
            max_y = min(self._world_state.height, anchor_y + size)
            return ChunkResponse(
                anchor_x=anchor_x,
                anchor_y=anchor_y,
                width=max_x - anchor_x,
                height=max_y - anchor_y,
                tiles=[
                    {
                        "x": tile.x,
                        "y": tile.y,
                        "terrain": tile.terrain.value,
                        "walkable": tile.walkable,
                    }
                    for tile in self._world_state.tiles
                    if anchor_x <= tile.x < max_x and anchor_y <= tile.y < max_y
                ],
                agents=[
                    agent.to_state_snapshot()
                    for agent in self._world_state.agents
                    if anchor_x <= agent.x < max_x and anchor_y <= agent.y < max_y
                ],
            )

    async def get_recent_world_events(self, limit: int = 20) -> list[WorldEventSchema]:
        """Return recent authoritative events as world-event DTOs."""

        async with self._lock:
            recent = self._recent_events[-limit:]
            start_index = max(0, len(self._recent_events) - len(recent))
            return [
                self._serialize_world_event(event, start_index + index)
                for index, event in enumerate(recent)
            ]

    async def seed_world(self, initial_agent_count: int | None = None) -> SimulationSnapshot:
        """Reset the current runtime to a clean seeded baseline."""

        async with self._lock:
            self._reset_world_state(initial_agent_count or len(self._world_state.agents))
            return self._world_state.to_snapshot()

    async def get_agent_relationships(self, agent_id: str) -> RelationshipsResponse:
        """Return a minimal relationship summary for an agent."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            if agent.partner_id is None:
                return RelationshipsResponse(relationships=[])
            return RelationshipsResponse(
                relationships=[
                    RelationshipSummary(
                        related_agent_id=agent.partner_id,
                        kind="partner",
                        score=1.0,
                    )
                ]
            )

    async def get_agent_goals(self, agent_id: str) -> GoalsResponse:
        """Return the current prototype goal state for an agent."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            return GoalsResponse(
                goals=[GoalSummary(title=agent.current_goal, status="active")] if agent.current_goal else []
            )

    async def get_agent_timeline(self, agent_id: str) -> TimelineResponse:
        """Return a simple merged memory and event timeline for an agent."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            entries = [
                TimelineEntry(kind="memory", summary=memory, tick=None)
                for memory in reversed(agent.memories[-10:])
            ]
            entries.extend(
                TimelineEntry(kind="event", summary=event.type.value, tick=event.tick)
                for event in reversed(self._recent_events[-20:])
                if event.agent_id == agent_id
            )
            return TimelineResponse(entries=entries)

    async def step_agent_once(self, agent_id: str) -> AgentStateSnapshot:
        """Advance one authoritative tick and return the specified agent snapshot."""

        async with self._lock:
            self._require_agent(agent_id)
            self._step_once_locked()
            return self._require_agent(agent_id).to_state_snapshot()

    async def force_reflect(self, agent_id: str) -> ForceReflectResponse:
        """Force a slow-loop pass for an agent on the next authoritative tick."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            agent.slow_loop_trigger_flags.add("major_life_event")
            self._step_once_locked()
            result = next((item for item in self._slow_loop_service.last_results if item.agent_id == agent_id), None)
            return ForceReflectResponse(
                agent_id=agent_id,
                applied=result.applied if result is not None else False,
                planner_hints=list(result.planner_hints) if result is not None else [],
                trigger_reasons=list(result.trigger_reasons) if result is not None else [],
            )

    async def get_memory_episodes(self, agent_id: str) -> EpisodesResponse:
        """Return prototype episodic memories stored on the authoritative agent state."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            return EpisodesResponse(
                episodes=[MemoryEpisodeSummary(text=memory, tick=None) for memory in reversed(agent.memories)]
            )

    async def get_daily_summary_candidates(self, agent_id: str) -> DailySummaryCandidatesResponse:
        """Return queued daily-summary candidates for one agent."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            return DailySummaryCandidatesResponse(
                agent_id=agent_id,
                day_index=agent.daily_summary_day_index,
                candidates=[
                    DailySummaryCandidateSummary(
                        text=candidate.text,
                        salience=candidate.salience,
                        valence=candidate.valence,
                    )
                    for candidate in agent.daily_summary_candidates
                ],
            )

    async def get_memory_beliefs(self, agent_id: str) -> BeliefsResponse:
        """Return prototype semantic beliefs stored on the authoritative agent state."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            return BeliefsResponse(beliefs=[BeliefSummary(text=belief) for belief in agent.beliefs])

    async def retrieve_memories(self, agent_id: str, query: str, limit: int) -> MemoryRetrieveResponse:
        """Perform simple substring retrieval against current agent memories."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            normalized = query.strip().lower()
            matches = [
                memory
                for memory in reversed(agent.memories)
                if not normalized or normalized in memory.lower()
            ]
            return MemoryRetrieveResponse(agent_id=agent_id, query=query, matches=matches[:limit])

    async def summarize_memories(self, agent_id: str) -> MemorySummarizeResponse:
        """Return a lightweight textual summary of recent memories."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            recent = self._memory_retriever.retrieve_recent_events(agent)[:3]
            return MemorySummarizeResponse(
                agent_id=agent_id,
                summary=" | ".join(recent) if recent else "No memories available.",
                memory_count=len(agent.memories),
            )

    async def get_debug_metrics(self) -> DebugMetricsResponse:
        """Return compact runtime metrics for debugging."""

        async with self._lock:
            last_tick = self._telemetry.tick_history[-1] if self._telemetry.tick_history else None
            return DebugMetricsResponse(
                tick=self._world_state.tick,
                sim_time=self._world_state.current_time.isoformat(),
                total_recorded_ticks=len(self._telemetry.tick_history),
                pending_scheduler_tasks=self._scheduler.pending_task_ids(),
                last_tick_event_count=last_tick.event_count if last_tick is not None else 0,
                last_tick_event_types=list(last_tick.event_types) if last_tick is not None else [],
                last_tick_event_type_counts=(
                    dict(last_tick.event_type_counts) if last_tick is not None else {}
                ),
            )

    async def get_replay_events(self, limit: int = 20) -> ReplayResponse:
        """Return recent authoritative events for replay/debugging."""

        async with self._lock:
            recent = self._recent_events[-limit:]
            start_index = max(0, len(self._recent_events) - len(recent))
            return ReplayResponse(
                events=[
                    ReplayEventResponse(
                        event_id=f"sim-{start_index + index}",
                        tick=event.tick,
                        event_type=event.type.value,
                        agent_id=event.agent_id,
                        sim_time=event.sim_time.isoformat(),
                        payload=dict(event.payload),
                    )
                    for index, event in enumerate(recent)
                ]
            )

    async def inspect_agent(self, agent_id: str) -> AgentInspectResponse:
        """Return a compact debug inspection payload for one agent."""

        async with self._lock:
            agent = self._require_agent(agent_id)
            return AgentInspectResponse(
                agent=agent.to_state_snapshot(),
                beliefs=list(agent.beliefs),
                memories=list(agent.memories),
                pending_planner_hints=list(agent.pending_planner_hints),
                trigger_flags=sorted(agent.slow_loop_trigger_flags),
            )

    async def inspect_household(self, household_id: str) -> HouseholdInspectResponse:
        """Return a minimal inspection payload for a prototype household."""

        async with self._lock:
            members = [
                agent.to_state_snapshot()
                for agent in self._world_state.agents
                if agent.household_id == household_id
            ]
            if not members:
                raise LookupError(f"Unknown household '{household_id}'.")
            return HouseholdInspectResponse(household_id=household_id, agents=members)

    async def spawn_agent(self, name: str | None, tile_x: int | None, tile_y: int | None) -> AgentStateSnapshot:
        """Create a new prototype agent in the authoritative world."""

        async with self._lock:
            next_index = len(self._world_state.agents) + 1
            agent = AgentState(
                agent_id=f"agent-{next_index}",
                name=name or f"Villager {next_index}",
                x=tile_x if tile_x is not None else min(self._world_state.width - 1, next_index - 1),
                y=tile_y if tile_y is not None else self._world_state.height // 2,
            )
            self._world_state.agents.append(agent)
            return agent.to_state_snapshot()

    async def spawn_food(self, tile_x: int, tile_y: int, quantity: int, item_type: str) -> SpawnFoodResponse:
        """Increase prototype world resources at a specific location."""

        async with self._lock:
            self._world_state.items.append(
                ItemStackState(
                    item_type=item_type,
                    x=tile_x,
                    y=tile_y,
                    quantity=quantity,
                )
            )
            self._world_state.resource_level += float(quantity)
            return SpawnFoodResponse(
                status="spawned",
                item_type=item_type,
                quantity=quantity,
                tile_x=tile_x,
                tile_y=tile_y,
                resource_level=self._world_state.resource_level,
            )

    async def advance_days(self, days: int) -> AdvanceDaysResponse:
        """Advance the simulation by coarse admin day units.

        The prototype keeps admin advancement responsive by approximating one day as 24 ticks.
        """

        async with self._lock:
            ticks_run = days * 24
            for _ in range(ticks_run):
                self._step_once_locked()
            return AdvanceDaysResponse(
                days_requested=days,
                ticks_run=ticks_run,
                final_tick=self._world_state.tick,
                current_time=self._world_state.current_time.isoformat(),
            )

    async def reset_world(self) -> ResetWorldResponse:
        """Reset the authoritative runtime to the initial baseline."""

        async with self._lock:
            self._reset_world_state(len(self._world_state.agents))
            return ResetWorldResponse(
                status="reset",
                tick=self._world_state.tick,
                agent_count=len(self._world_state.agents),
            )

    async def emit_simulation_event(
        self,
        event_type: EventType,
        agent_id: str | None = None,
        payload: dict[str, object] | None = None,
        actor_ids: list[str] | None = None,
        target_ids: list[str] | None = None,
        location_x: int | None = None,
        location_y: int | None = None,
        source_module: str | None = None,
    ) -> None:
        """Enqueue an authoritative simulation event for the next world tick."""

        async with self._lock:
            self._event_bus.emit(
                SimulationEvent(
                    type=event_type,
                    tick=self._world_state.tick,
                    sim_time=self._world_state.current_time,
                    agent_id=agent_id,
                    actor_ids=list(actor_ids or []),
                    target_ids=list(target_ids or []),
                    location_x=location_x,
                    location_y=location_y,
                    source_module=source_module or "runtime",
                    payload=payload or {},
                )
            )

    async def get_debug_state(self) -> dict[str, object]:
        """Return lightweight debug state for the current simulation runtime."""

        async with self._lock:
            return {
                "tick": self._world_state.tick,
                "sim_time": self._world_state.current_time.isoformat(),
                "weather": self._world_state.weather,
                "pending_scheduler_tasks": self._scheduler.pending_task_ids(),
                "last_fast_loop_traces": [
                    {
                        "agent_id": trace.agent_id,
                        "stage_order": list(trace.stage_order),
                        "perception_summary": dict(trace.perception_summary),
                        "top_action_candidates": [dict(candidate) for candidate in trace.top_action_candidates],
                        "selected_action": trace.selected_action,
                        "planned_tasks": list(trace.planned_tasks),
                        "planner_hints_before": list(trace.planner_hints_before),
                        "planner_hints_after": list(trace.planner_hints_after),
                        "emitted_event_types": list(trace.emitted_event_types),
                    }
                    for trace in self._agent_runtime.last_step_traces
                ],
                "last_fast_loop_event_types": list(self._agent_runtime.last_fast_loop_event_types),
                "last_lifecycle_event_types": list(self._agent_runtime.last_lifecycle_event_types),
                "last_slow_loop_event_types": list(self._agent_runtime.last_slow_loop_event_types),
                "last_slow_loop_results": [
                    {
                        "agent_id": result.agent_id,
                        "trigger_reasons": list(result.trigger_reasons),
                        "applied": result.applied,
                        "planner_hints": list(result.planner_hints),
                    }
                    for result in self._slow_loop_service.last_results
                ],
                "last_tick_telemetry": (
                    {
                        "tick": self._telemetry.tick_history[-1].tick,
                        "stage_order": list(self._telemetry.tick_history[-1].stage_order),
                        "event_count": self._telemetry.tick_history[-1].event_count,
                        "event_types": list(self._telemetry.tick_history[-1].event_types),
                        "event_type_counts": dict(self._telemetry.tick_history[-1].event_type_counts),
                    }
                    if self._telemetry.tick_history
                    else None
                ),
            }

    def _get_agent(self, agent_id: str) -> AgentState | None:
        """Look up an agent by its authoritative identifier."""

        for agent in self._world_state.agents:
            if agent.agent_id == agent_id:
                return agent
        return None

    def _require_agent(self, agent_id: str) -> AgentState:
        """Look up an agent by id and raise a consistent error when missing."""

        agent = self._get_agent(agent_id)
        if agent is None:
            raise LookupError(f"Unknown agent '{agent_id}'.")
        return agent

    def _step_once_locked(self) -> SimulationSnapshot:
        """Advance one tick while the caller holds the runtime lock."""

        snapshot = self._world_loop.tick_once()
        if self._telemetry.last_flushed_events:
            self._replay_log.record(self._telemetry.last_flushed_events[-1])
        self._recent_events = self._replay_log.recent_events(limit=200)
        return snapshot

    def _reset_world_state(self, initial_agent_count: int) -> None:
        """Rebuild the world, clock, scheduler, and telemetry to a clean baseline."""

        self._world_state = build_initial_world_state(
            width=self._world_state.width,
            height=self._world_state.height,
            initial_agent_count=initial_agent_count,
        )
        self._scheduler = TaskScheduler()
        self._telemetry = TelemetryRecorder()
        self._replay_log = ReplayEventLog(max_events=200)
        self._event_bus = self._build_event_bus()
        self._recent_events = []
        self._sim_clock = SimulationClock(
            start_time=self._world_state.current_time,
            tick_interval=timedelta(seconds=self._tick_interval_seconds),
        )
        self._world_loop = WorldLoop(
            world_state=self._world_state,
            sim_clock=self._sim_clock,
            scheduler=self._scheduler,
            agent_runtime=self._agent_runtime,
            telemetry=self._telemetry,
            event_bus=self._event_bus,
        )

    def _serialize_world_event(self, event: SimulationEvent, index: int) -> WorldEventSchema:
        """Adapt a recent simulation event into the shared world-event DTO."""

        return WorldEventSchema.from_simulation_event(
            event,
            fallback_event_id=f"{event.tick}-{index}-{event.type.value}",
        )

    def _build_event_bus(self) -> EventBus:
        """Create and subscribe the authoritative event bus for the current runtime state."""

        event_bus = EventBus()
        event_bus.subscribe_all(self._telemetry.observe_event)
        event_bus.subscribe_all(self._replay_log.handle)
        event_bus.subscribe_all(
            MemoryPipelineListener(
                lambda: self._world_state,
                memory_writer=MemoryWriter(),
                session_scope=self._world_event_session_scope,
                resolve_agent_id=self._persistent_agent_id_resolver,
                embedding_provider=self._memory_embedding_provider,
            ).handle
        )
        event_bus.subscribe_all(RelationshipEventListener(lambda: self._world_state).handle)
        if self._world_event_session_scope is not None:
            event_bus.subscribe_all(
                WorldEventPersistenceListener(
                    self._world_event_session_scope,
                    resolve_agent_id=self._persistent_agent_id_resolver,
                ).handle
            )
        return event_bus
