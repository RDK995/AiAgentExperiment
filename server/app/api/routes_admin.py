"""Admin routes for coarse prototype world control."""

from fastapi import APIRouter, Depends, Path

from app.api.dependencies import get_runtime
from app.api.errors import error_responses
from app.engine.tick_loop import SimulationRuntime
from app.schemas.api import (
    AdvanceDaysResponse,
    ResetWorldResponse,
    SpawnAgentRequest,
    SpawnAgentResponse,
    SpawnFoodRequest,
    SpawnFoodResponse,
)

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/spawn-agent", response_model=SpawnAgentResponse)
async def spawn_agent(
    payload: SpawnAgentRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> SpawnAgentResponse:
    """Spawn a prototype agent into the authoritative world."""

    agent = await runtime.spawn_agent(
        name=payload.name,
        tile_x=payload.tile_x,
        tile_y=payload.tile_y,
    )
    return SpawnAgentResponse(status="spawned", agent=agent)


@router.post("/spawn-food", response_model=SpawnFoodResponse)
async def spawn_food(
    payload: SpawnFoodRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> SpawnFoodResponse:
    """Increase prototype world food/resources at the requested tile."""

    return await runtime.spawn_food(
        tile_x=payload.tile_x,
        tile_y=payload.tile_y,
        quantity=payload.quantity,
        item_type=payload.item_type,
    )


@router.post(
    "/advance-days/{days}",
    response_model=AdvanceDaysResponse,
    responses=error_responses(400),
)
async def advance_days(
    days: int = Path(ge=1, le=30),
    runtime: SimulationRuntime = Depends(get_runtime),
) -> AdvanceDaysResponse:
    """Advance the simulation by a coarse number of prototype days."""

    return await runtime.advance_days(days)


@router.post("/reset-world", response_model=ResetWorldResponse)
async def reset_world(runtime: SimulationRuntime = Depends(get_runtime)) -> ResetWorldResponse:
    """Reset the authoritative runtime to a clean deterministic baseline."""

    return await runtime.reset_world()
