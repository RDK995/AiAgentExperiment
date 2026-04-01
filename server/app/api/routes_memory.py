"""Memory-centric authoritative backend routes."""

from fastapi import APIRouter, Depends

from app.api.errors import error_responses, not_found
from app.api.dependencies import get_runtime
from app.engine.tick_loop import SimulationRuntime
from app.schemas.api import (
    BeliefsResponse,
    EpisodesResponse,
    MemoryRetrieveRequest,
    MemoryRetrieveResponse,
    MemorySummarizeResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])


@router.get("/{agent_id}/episodes", response_model=EpisodesResponse, responses=error_responses(404))
async def get_agent_episodes(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> EpisodesResponse:
    """Return prototype episodic memories for one agent."""

    try:
        return await runtime.get_memory_episodes(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.get("/{agent_id}/beliefs", response_model=BeliefsResponse, responses=error_responses(404))
async def get_agent_beliefs(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> BeliefsResponse:
    """Return prototype semantic beliefs for one agent."""

    try:
        return await runtime.get_memory_beliefs(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.post("/{agent_id}/retrieve", response_model=MemoryRetrieveResponse, responses=error_responses(404))
async def retrieve_memories(
    agent_id: str,
    payload: MemoryRetrieveRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> MemoryRetrieveResponse:
    """Retrieve matching memories from the authoritative agent state."""

    try:
        return await runtime.retrieve_memories(agent_id, query=payload.query, limit=payload.limit)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.post("/{agent_id}/summarize", response_model=MemorySummarizeResponse, responses=error_responses(404))
async def summarize_memories(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> MemorySummarizeResponse:
    """Return a lightweight summary of the agent's stored memories."""

    try:
        return await runtime.summarize_memories(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc
