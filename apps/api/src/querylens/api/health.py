"""Health check endpoints (liveness and readiness)."""

from __future__ import annotations

from typing import Callable
from fastapi import APIRouter, Response, status
from pydantic import BaseModel

router = APIRouter(prefix="/health", tags=["health"])

_metadata_probe: Callable[[], bool] | None = None


def set_metadata_probe(probe: Callable[[], bool] | None) -> None:
    """Inject probe function for testing or lifecycle management."""
    global _metadata_probe
    _metadata_probe = probe


def check_metadata_db() -> bool:
    """Probe metadata database availability."""
    if _metadata_probe is not None:
        try:
            return _metadata_probe()
        except Exception:
            return False
    return True


class HealthResponse(BaseModel):
    status: str
    metadata_db: str | None = None


@router.get("", response_model=HealthResponse)
async def health(response: Response) -> HealthResponse:
    """General health check endpoint for proxy and smoke tests."""
    is_ready = check_metadata_db()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="degraded", metadata_db="unreachable")
    return HealthResponse(status="ok", metadata_db="healthy")


@router.get("/live", response_model=HealthResponse)
async def liveness() -> HealthResponse:
    """Liveness probe: returns 200 if the process and event loop are alive."""
    return HealthResponse(status="alive")


@router.get("/ready", response_model=HealthResponse)
async def readiness(response: Response) -> HealthResponse:
    """Readiness probe: returns 200 if metadata DB is reachable, 503 otherwise."""
    is_ready = check_metadata_db()
    if not is_ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthResponse(status="unready", metadata_db="unreachable")
    return HealthResponse(status="ready", metadata_db="healthy")
