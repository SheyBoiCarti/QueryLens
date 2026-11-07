"""Schema discovery, catalog reflection, and refresh endpoints (Contracts C02, C05)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, status

from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.domain.schema import CatalogSnapshot
from querylens.schema.catalog import CatalogService

router = APIRouter(prefix="/connections/{connection_id}/schema", tags=["schema"])


def get_catalog_service() -> CatalogService:
    return CatalogService()


@router.get("/discover", response_model=list[str])
async def discover_tables(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> list[str]:
    """Discover candidate table names in approved namespaces without sampling rows."""
    return service.discover_tables(current_user["user_id"], connection_id)


@router.get("", response_model=CatalogSnapshot)
async def get_catalog(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> CatalogSnapshot:
    """Get the current reflected schema snapshot for authorized visible objects."""
    return service.get_catalog(current_user["user_id"], connection_id)


@router.post("/refresh", response_model=CatalogSnapshot)
async def refresh_catalog(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
    service: CatalogService = Depends(get_catalog_service),
) -> CatalogSnapshot:
    """Trigger reflection and atomically update the catalog snapshot."""
    return service.refresh_catalog(current_user["user_id"], connection_id)
