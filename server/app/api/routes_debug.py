"""Debug and inspection routes for the authoritative backend."""

from fastapi import APIRouter, Depends, Query

from app.api.errors import error_responses, not_found
from app.api.dependencies import get_runtime
from app.engine.tick_loop import SimulationRuntime
from app.schemas.api import (
    AgentInspectResponse,
    DebugMetricsResponse,
    HouseholdInspectResponse,
    ReplayResponse,
)

router = APIRouter(prefix="/debug", tags=["debug"])


@router.get("/metrics", response_model=DebugMetricsResponse)
async def get_metrics(runtime: SimulationRuntime = Depends(get_runtime)) -> DebugMetricsResponse:
    """Return high-level runtime metrics for debugging."""

    return await runtime.get_debug_metrics()


@router.get("/replay", response_model=ReplayResponse)
async def get_replay(
    limit: int = Query(default=20, ge=1, le=100),
    runtime: SimulationRuntime = Depends(get_runtime),
) -> ReplayResponse:
    """Return recent authoritative events in replay-friendly form."""

    return await runtime.get_replay_events(limit=limit)


@router.get("/inspect/agent/{agent_id}", response_model=AgentInspectResponse, responses=error_responses(404))
async def inspect_agent(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> AgentInspectResponse:
    """Return a compact inspection payload for one agent."""

    try:
        return await runtime.inspect_agent(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.get(
    "/inspect/household/{household_id}",
    response_model=HouseholdInspectResponse,
    responses=error_responses(404),
)
async def inspect_household(
    household_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> HouseholdInspectResponse:
    """Return a minimal household inspection payload."""

    try:
        return await runtime.inspect_household(household_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
