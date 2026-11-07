"""Business Metrics API endpoints (Contracts C02, C05, C10)."""

from __future__ import annotations

import datetime
import json
import uuid
from typing import Any
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel
import sqlalchemy as sa

from querylens.api.errors import NotFoundError
from querylens.api.schemas import StatusResponse
from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.auth.ownership import verify_connection_ownership
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import business_metrics
from querylens.schema.catalog import CatalogService
from querylens.semantics.metrics import MetricDSL

router = APIRouter(prefix="/connections/{connection_id}/metrics", tags=["metrics"])


class MetricResponse(BaseModel):
    id: str
    connection_id: str
    key: str
    name: str
    description: str | None
    dsl: MetricDSL
    version: int
    enabled: bool


@router.post("", response_model=MetricResponse, status_code=status.HTTP_201_CREATED)
async def create_metric(
    connection_id: str,
    payload: MetricDSL,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> MetricResponse:
    """Create a structured business metric validated against the connection catalog."""
    user_id = current_user["user_id"]
    verify_connection_ownership(connection_id, user_id)

    # Validate against visible catalog snapshot
    catalog = CatalogService().get_catalog(user_id, connection_id)
    payload.validate_against_snapshot(catalog)

    metric_id = str(uuid.uuid4())
    now = datetime.datetime.now(datetime.timezone.utc)
    dsl_json = json.dumps(payload.model_dump())

    stmt = business_metrics.insert().values(
        id=metric_id,
        connection_id=connection_id,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        dsl_json=dsl_json,
        version=1,
        enabled=True,
        created_at=now,
        updated_at=now,
    )
    with get_db_connection() as conn:
        conn.execute(stmt)

    return MetricResponse(
        id=metric_id,
        connection_id=connection_id,
        key=payload.key,
        name=payload.name,
        description=payload.description,
        dsl=payload,
        version=1,
        enabled=True,
    )


@router.get("", response_model=list[MetricResponse])
async def list_metrics(
    connection_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> list[MetricResponse]:
    """List business metrics defined for connection."""
    user_id = current_user["user_id"]
    verify_connection_ownership(connection_id, user_id)

    stmt = sa.select(business_metrics).where(business_metrics.c.connection_id == connection_id)
    with get_db_connection() as conn:
        rows = conn.execute(stmt).fetchall()

    results = []
    for r in rows:
        m = dict(r._mapping)
        dsl_data = json.loads(m["dsl_json"])
        results.append(
            MetricResponse(
                id=m["id"],
                connection_id=m["connection_id"],
                key=m["key"],
                name=m["name"],
                description=m["description"],
                dsl=MetricDSL.model_validate(dsl_data),
                version=m["version"],
                enabled=m["enabled"],
            )
        )
    return results


@router.delete("/{metric_id}", response_model=StatusResponse)
async def delete_metric(
    connection_id: str,
    metric_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> StatusResponse:
    """Delete business metric."""
    user_id = current_user["user_id"]
    verify_connection_ownership(connection_id, user_id)

    stmt = business_metrics.delete().where(
        business_metrics.c.id == metric_id,
        business_metrics.c.connection_id == connection_id,
    )
    with get_db_connection() as conn:
        res = conn.execute(stmt)

    if res.rowcount == 0:
        raise NotFoundError("Metric not found")

    return StatusResponse(status="deleted")
