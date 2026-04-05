"""World and simulation control routes."""

import asyncio

from fastapi import APIRouter, Depends, Query
from fastapi import WebSocket, WebSocketDisconnect

from app.api.errors import bad_request, conflict, error_responses, not_found
from app.api.dependencies import get_runtime
from app.engine.tick_loop import SimulationRuntime
from app.schemas.agent import AgentStateSnapshot
from app.schemas.api import (
    AgentListResponse,
    ChunkResponse,
    MoveAgentRequest,
    RecentWorldEventsResponse,
    RunSimulationRequest,
    SeedResponse,
    SimulationSnapshot,
    WorldStreamBatchResponse,
    WorldStreamEnvelope,
    WorldSeedRequest,
    WorldSeedDefinitionResponse,
)
from app.services.world_seed_service import WorldSeedService

router = APIRouter(prefix="/world", tags=["world"])


@router.get("/snapshot", response_model=SimulationSnapshot)
async def get_world_snapshot(runtime: SimulationRuntime = Depends(get_runtime)) -> SimulationSnapshot:
    """Return the latest authoritative world snapshot."""

    return await runtime.get_snapshot()


@router.get("/state", response_model=SimulationSnapshot)
async def get_world_state(runtime: SimulationRuntime = Depends(get_runtime)) -> SimulationSnapshot:
    """Return the latest authoritative world state snapshot."""

    return await runtime.get_snapshot()


@router.get("/agents", response_model=AgentListResponse)
async def get_agent_snapshots(runtime: SimulationRuntime = Depends(get_runtime)) -> AgentListResponse:
    """Return richer backend-facing snapshots for all authoritative agents."""

    return AgentListResponse(agents=await runtime.get_agent_snapshots())


@router.get(
    "/agents/{agent_id}",
    response_model=AgentStateSnapshot,
    responses=error_responses(404),
)
async def get_agent_snapshot(
    agent_id: str,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> AgentStateSnapshot:
    """Return a richer backend-facing snapshot for a specific authoritative agent."""

    try:
        return await runtime.get_agent_snapshot(agent_id)
    except LookupError as exc:
        raise not_found(str(exc)) from exc


@router.post("/tick", response_model=SimulationSnapshot)
async def step_world_once(runtime: SimulationRuntime = Depends(get_runtime)) -> SimulationSnapshot:
    """Advance the simulation by a single authoritative tick."""

    return await runtime.step_once()


@router.post("/run", response_model=SimulationSnapshot)
async def run_world(
    payload: RunSimulationRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> SimulationSnapshot:
    """Advance the simulation by a client-requested number of ticks."""

    return await runtime.run_for_ticks(payload.ticks)


@router.post("/tick/run", response_model=SimulationSnapshot)
async def run_world_ticks(
    payload: RunSimulationRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> SimulationSnapshot:
    """Advance the simulation by one or more authoritative ticks."""

    return await runtime.run_for_ticks(payload.ticks)


@router.get(
    "/chunk/{x}/{y}",
    response_model=ChunkResponse,
    responses=error_responses(400),
)
async def get_world_chunk(
    x: int,
    y: int,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> ChunkResponse:
    """Return a deterministic chunk view anchored at the requested tile."""

    if x < 0 or y < 0:
        raise bad_request("Chunk coordinates must be non-negative.")
    try:
        return await runtime.get_world_chunk(x, y)
    except ValueError as exc:
        raise bad_request(str(exc)) from exc


@router.get("/events/recent", response_model=RecentWorldEventsResponse)
async def get_recent_world_events(
    limit: int = Query(default=20, ge=1, le=100),
    runtime: SimulationRuntime = Depends(get_runtime),
) -> RecentWorldEventsResponse:
    """Return the most recent authoritative world events."""

    return RecentWorldEventsResponse(events=await runtime.get_recent_world_events(limit=limit))


@router.websocket("/stream")
async def stream_world_events(websocket: WebSocket) -> None:
    """Stream authoritative seed bootstrap and snapshot/event batches to clients."""

    await websocket.accept()

    app_state = websocket.app.state
    runtime: SimulationRuntime = app_state.simulation_runtime
    requested_seed_id = websocket.query_params.get("seed_id")
    seed_on_connect = websocket.query_params.get("seed_on_connect", "false").lower() == "true"
    poll_seconds_raw = websocket.query_params.get("poll_seconds", "0.25")

    try:
        poll_seconds = min(5.0, max(0.05, float(poll_seconds_raw)))
    except ValueError:
        poll_seconds = 0.25

    try:
        if seed_on_connect and requested_seed_id is not None:
            await runtime.seed_world(seed_id=requested_seed_id)
    except ValueError as exc:
        await websocket.send_json(
            WorldStreamEnvelope(
                message_type="warning",
                warning=str(exc),
            ).model_dump(mode="json")
        )
        await websocket.close(code=1008, reason=str(exc))
        return

    current_seed_id = runtime.get_current_seed_id()
    if current_seed_id is not None:
        await websocket.send_json(
            WorldStreamEnvelope(
                message_type="seed_definition",
                seed_definition=WorldSeedService().load_seed_definition(current_seed_id),
            ).model_dump(mode="json")
        )
    else:
        await websocket.send_json(
            WorldStreamEnvelope(
                message_type="warning",
                warning="No fixed world seed is active on the backend; streaming snapshot-only state.",
            ).model_dump(mode="json")
        )

    last_tick = -1
    last_event_id = ""
    last_seed_id = current_seed_id

    try:
        while True:
            try:
                await asyncio.wait_for(websocket.receive_text(), timeout=poll_seconds)
            except asyncio.TimeoutError:
                pass

            current_seed_id = runtime.get_current_seed_id()
            if current_seed_id != last_seed_id and current_seed_id is not None:
                await websocket.send_json(
                    WorldStreamEnvelope(
                        message_type="seed_definition",
                        seed_definition=WorldSeedService().load_seed_definition(current_seed_id),
                    ).model_dump(mode="json")
                )
                last_seed_id = current_seed_id

            snapshot = await runtime.get_snapshot()
            events = await runtime.get_recent_world_events(limit=20)
            latest_event_id = events[-1].event_id if events else ""
            if snapshot.tick == last_tick and latest_event_id == last_event_id:
                continue

            await websocket.send_json(
                WorldStreamEnvelope(
                    message_type="snapshot_batch",
                    snapshot_batch=WorldStreamBatchResponse(
                        snapshot=snapshot,
                        events=events,
                    ),
                ).model_dump(mode="json")
            )
            last_tick = snapshot.tick
            last_event_id = latest_event_id
    except WebSocketDisconnect:
        return


@router.post("/seed", response_model=SeedResponse)
async def seed_world(
    payload: WorldSeedRequest | None = None,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> SeedResponse:
    """Reset and reseed the world to a clean deterministic baseline."""

    requested_seed_id = payload.seed_id if payload is not None else None
    snapshot = await runtime.seed_world(
        initial_agent_count=payload.agent_count if payload is not None else None,
        seed_id=requested_seed_id,
    )
    return SeedResponse(
        status="seeded",
        tick=snapshot.tick,
        width=snapshot.world.width,
        height=snapshot.world.height,
        seeded_agents=len(snapshot.agents),
        seed_id=requested_seed_id,
    )


@router.get(
    "/seeds/{seed_id}",
    response_model=WorldSeedDefinitionResponse,
    responses=error_responses(404),
)
async def get_world_seed_definition(seed_id: str) -> WorldSeedDefinitionResponse:
    """Return one deterministic world seed definition for client bootstrap/debugging."""

    try:
        return WorldSeedService().load_seed_definition(seed_id)
    except ValueError as exc:
        raise not_found(str(exc)) from exc


@router.post(
    "/actions/move",
    response_model=SimulationSnapshot,
    responses=error_responses(404, 409),
)
async def move_agent(
    payload: MoveAgentRequest,
    runtime: SimulationRuntime = Depends(get_runtime),
) -> SimulationSnapshot:
    """Attempt an authoritative move action for a specific agent."""

    try:
        return await runtime.move_agent(
            agent_id=payload.agent_id,
            target_x=payload.target_x,
            target_y=payload.target_y,
        )
    except LookupError as exc:
        raise not_found(str(exc)) from exc
    except ValueError as exc:
        raise conflict(str(exc)) from exc
