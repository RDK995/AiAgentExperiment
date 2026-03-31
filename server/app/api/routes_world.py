"""World and simulation control routes."""

from fastapi import APIRouter, HTTPException, Request, status

from app.engine.tick_loop import SimulationRuntime
from app.schemas.api import MoveAgentRequest, RunSimulationRequest, SimulationSnapshot

router = APIRouter(prefix="/world", tags=["world"])


def get_runtime(request: Request) -> SimulationRuntime:
    """Resolve the shared simulation runtime from application state."""

    return request.app.state.simulation_runtime


@router.get("/snapshot", response_model=SimulationSnapshot)
async def get_world_snapshot(request: Request) -> SimulationSnapshot:
    """Return the latest authoritative world snapshot."""

    runtime = get_runtime(request)
    return await runtime.get_snapshot()


@router.get("/state", response_model=SimulationSnapshot)
async def get_world_state(request: Request) -> SimulationSnapshot:
    """Return the latest authoritative world state snapshot."""

    runtime = get_runtime(request)
    return await runtime.get_snapshot()


@router.post("/tick", response_model=SimulationSnapshot)
async def step_world_once(request: Request) -> SimulationSnapshot:
    """Advance the simulation by a single authoritative tick."""

    runtime = get_runtime(request)
    return await runtime.step_once()


@router.post("/run", response_model=SimulationSnapshot)
async def run_world(
    payload: RunSimulationRequest,
    request: Request,
) -> SimulationSnapshot:
    """Advance the simulation by a client-requested number of ticks."""

    runtime = get_runtime(request)
    return await runtime.run_for_ticks(payload.ticks)


@router.post("/actions/move", response_model=SimulationSnapshot)
async def move_agent(
    payload: MoveAgentRequest,
    request: Request,
) -> SimulationSnapshot:
    """Attempt an authoritative move action for a specific agent."""

    runtime = get_runtime(request)

    try:
        return await runtime.move_agent(
            agent_id=payload.agent_id,
            target_x=payload.target_x,
            target_y=payload.target_y,
        )
    except LookupError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
