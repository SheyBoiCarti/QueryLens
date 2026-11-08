"""Connection API endpoints (Contracts C01, C02, C03, C04)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, status

from querylens.api.schemas import StatusResponse
from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.connections.models import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionTestResponse,
    ConnectionUpdate,
)
from querylens.connections.service import ConnectionService

router = APIRouter(prefix="/connections", tags=["connections"])


def get_connection_service() -> ConnectionService:
    return ConnectionService()


@router.post("", response_model=ConnectionResponse, status_code=status.HTTP_201_CREATED)
def create_connection(
    payload: ConnectionCreate,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionResponse:
    """Create a new database connection."""
    return service.create(current_user["user_id"], payload)


@router.get("", response_model=list[ConnectionResponse])
def list_connections(
    current_user: dict[str, Any] = Depends(get_current_user),
    service: ConnectionService = Depends(get_connection_service),
) -> list[ConnectionResponse]:
    """List all connections owned by current user."""
    return service.list_all(current_user["user_id"])


@router.get("/{connection_id}", response_model=ConnectionResponse)
def get_connection(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionResponse:
    """Get connection details."""
    return service.get(current_user["user_id"], connection_id)


@router.patch("/{connection_id}", response_model=ConnectionResponse)
def update_connection(
    connection_id: str,
    payload: ConnectionUpdate,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionResponse:
    """Update connection details. Omitted password preserves existing secret."""
    return service.update(current_user["user_id"], connection_id, payload)


@router.delete("/{connection_id}", response_model=StatusResponse)
def delete_connection(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
    service: ConnectionService = Depends(get_connection_service),
) -> StatusResponse:
    """Delete connection and dispose its pools."""
    service.delete(current_user["user_id"], connection_id)
    return StatusResponse(status="deleted")


@router.post("/{connection_id}/test", response_model=ConnectionTestResponse)
def test_connection_endpoint(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
    service: ConnectionService = Depends(get_connection_service),
) -> ConnectionTestResponse:
    """Test connection using target adapter."""
    return service.test(current_user["user_id"], connection_id)
