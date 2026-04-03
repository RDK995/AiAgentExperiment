"""Shared API error helpers and response metadata."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.schemas.api import ErrorResponse


class ApiError(Exception):
    """Structured route-layer exception for consistent JSON error payloads."""

    def __init__(self, *, status_code: int, error: str, message: str) -> None:
        self.status_code = status_code
        self.error = error
        self.message = message
        super().__init__(message)


def register_api_error_handlers(app: FastAPI) -> None:
    """Register the shared API error handler on the FastAPI app."""

    @app.exception_handler(ApiError)
    async def _handle_api_error(request: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorResponse(error=exc.error, message=exc.message).model_dump(mode="json"),
        )


def error_responses(*status_codes: int) -> dict[int, dict[str, object]]:
    """Generate reusable OpenAPI error response metadata."""

    details: dict[int, dict[str, object]] = {}
    for code in status_codes:
        description = {
            400: "Bad Request",
            404: "Not Found",
            409: "Conflict",
        }.get(code, "Error")
        details[code] = {"model": ErrorResponse, "description": description}
    return details


def bad_request(message: str) -> ApiError:
    """Build a standardized bad-request exception."""

    return ApiError(status_code=400, error="bad_request", message=message)


def not_found(message: str) -> ApiError:
    """Build a standardized not-found exception."""

    return ApiError(status_code=404, error="not_found", message=message)


def conflict(message: str) -> ApiError:
    """Build a standardized conflict exception."""

    return ApiError(status_code=409, error="conflict", message=message)
