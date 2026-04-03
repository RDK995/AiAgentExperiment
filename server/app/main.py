"""FastAPI application entrypoint for the authoritative simulation backend."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_api_error_handlers
from app.api.routes_admin import router as admin_router
from app.api.routes_agents import router as agents_router
from app.api.routes_debug import router as debug_router
from app.api.routes_memory import router as memory_router
from app.api.routes_world import router as world_router
from app.config import get_settings
from app.engine.tick_loop import SimulationRuntime
from app.engine.world_state import build_initial_world_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create shared simulation services and manage their lifecycle."""

    settings = get_settings()
    initial_world = build_initial_world_state(
        width=settings.world_width,
        height=settings.world_height,
        initial_agent_count=settings.initial_agent_count,
    )
    runtime = SimulationRuntime(
        initial_state=initial_world,
        tick_interval_seconds=settings.tick_interval_seconds,
    )
    app.state.simulation_runtime = runtime
    await runtime.start()
    try:
        yield
    finally:
        await runtime.stop()


settings = get_settings()
def create_app() -> FastAPI:
    """Build an application instance with its own simulation runtime."""

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    register_api_error_handlers(app)
    app.include_router(world_router, prefix="/api/v1")
    app.include_router(agents_router, prefix="/api/v1")
    app.include_router(memory_router, prefix="/api/v1")
    app.include_router(debug_router, prefix="/api/v1")
    app.include_router(admin_router, prefix="/api/v1")

    @app.get("/health", tags=["health"])
    async def healthcheck() -> dict[str, str]:
        """Basic healthcheck endpoint for local development and orchestration."""

        return {"status": "ok"}

    return app


app = create_app()
