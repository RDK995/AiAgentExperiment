"""Shared FastAPI dependencies for authoritative backend routes."""

from __future__ import annotations

from fastapi import Request

from app.engine.tick_loop import SimulationRuntime


def get_runtime(request: Request) -> SimulationRuntime:
    """Resolve the shared simulation runtime from application state."""

    return request.app.state.simulation_runtime
