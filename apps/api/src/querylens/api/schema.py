"""Schema discovery, catalog reflection, and refresh endpoints (Contracts C02, C05)."""

from __future__ import annotations

from typing import Any, Callable, TypeVar
import sqlalchemy as sa

from querylens.api.errors import AppError
from querylens.connections.network import NetworkSecurityError
from fastapi import APIRouter, Depends

from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.domain.schema import CatalogSnapshot
from querylens.schema.catalog import CatalogService
from querylens.utils.workers import run_db

router = APIRouter(prefix="/connections/{connection_id}/schema", tags=["schema"])


T = TypeVar("T")


async def run_schema_operation(operation: Callable[..., T], *args: Any) -> T:
    try:
        return await run_db(operation, *args, timeout_sec=60.0)
    except TimeoutError as exc:
        raise AppError("SCHEMA_TIMEOUT", "Schema discovery took too long. Please try again.", 504) from exc
    except (sa.exc.SQLAlchemyError, NetworkSecurityError, OSError) as exc:
        raise AppError(
            "SCHEMA_DISCOVERY_FAILED",
            "Could not read the database schema. Test the connection and check this user's table metadata permissions, then try again.",
            422,
        ) from exc


def get_catalog_service() -> CatalogService:
    return CatalogService()


@router.get("/discover", response_model=list[str])
async def discover_tables(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> list[str]:
    """Discover candidate table names in approved namespaces without sampling rows."""
    return await run_schema_operation(service.discover_tables, current_user["user_id"], connection_id)


@router.get("/discover/columns", response_model=dict[str, list[str]])
async def discover_columns(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> dict[str, list[str]]:
    return await run_schema_operation(service.discover_columns, current_user["user_id"], connection_id)


@router.get("", response_model=CatalogSnapshot)
async def get_catalog(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    service: CatalogService = Depends(get_catalog_service),
) -> CatalogSnapshot:
    """Get the current reflected schema snapshot for authorized visible objects."""
    return await run_schema_operation(service.get_catalog, current_user["user_id"], connection_id)


@router.post("/refresh", response_model=CatalogSnapshot)
async def refresh_catalog(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
    service: CatalogService = Depends(get_catalog_service),
) -> CatalogSnapshot:
    """Trigger reflection and atomically update the catalog snapshot."""
    return await run_schema_operation(service.refresh_catalog, current_user["user_id"], connection_id)
