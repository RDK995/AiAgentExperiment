"""Agent-centric authoritative backend routes."""

from fastapi import APIRouter, Depends

from app.api.errors import error_responses, not_found
from app.api.dependencies import get_runtime
from app.engine.tick_loop import SimulationRuntime
from app.schemas.agent import AgentStateSnapshot
from app.schemas.api import (
    AgentListResponse,
    ForceReflectResponse,
    GoalsResponse,
    RelationshipsResponse,
    TimelineResponse,
)

router = APIRouter(prefix="/agents", tags=["agents"])


@router.get("", response_model=AgentListResponse)
async def list_agents(runtime: SimulationRuntime = Depends(get_runtime)) -> AgentListResponse:
    """Return all authoritative agents as rich inspection snapshots."""

    return AgentListResponse(agents=await runtime.get_agent_snapshots())


@router.get("/{agent_id}", response_model=AgentStateSnapshot, responses=error_responses(404))
async def get_agent(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> AgentStateSnapshot:
    """Return one authoritative agent snapshot."""

    try:
        return await runtime.get_agent_snapshot(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.get(
    "/{agent_id}/relationships",
    response_model=RelationshipsResponse,
    responses=error_responses(404),
)
async def get_agent_relationships(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> RelationshipsResponse:
    """Return the current relationship summary for one agent."""

    try:
        return await runtime.get_agent_relationships(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.get("/{agent_id}/goals", response_model=GoalsResponse, responses=error_responses(404))
async def get_agent_goals(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> GoalsResponse:
    """Return the current prototype goal state for one agent."""

    try:
        return await runtime.get_agent_goals(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.get("/{agent_id}/timeline", response_model=TimelineResponse, responses=error_responses(404))
async def get_agent_timeline(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> TimelineResponse:
    """Return a simple merged timeline for one agent."""

    try:
        return await runtime.get_agent_timeline(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.post("/{agent_id}/step", response_model=AgentStateSnapshot, responses=error_responses(404))
async def step_agent(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> AgentStateSnapshot:
    """Advance the authoritative simulation once and return the selected agent."""

    try:
        return await runtime.step_agent_once(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.post(
    "/{agent_id}/force-reflect",
    response_model=ForceReflectResponse,
    responses=error_responses(404),
)
async def force_reflect(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> ForceReflectResponse:
    """Force the selected agent through the slow-loop reflection path."""

    try:
        return await runtime.force_reflect(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
