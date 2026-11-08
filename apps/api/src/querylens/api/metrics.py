"""Versioned, owner-scoped business metrics (Contracts C02, C05, C10)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, model_validator
import sqlalchemy as sa

from querylens.api.errors import NotFoundError
from querylens.api.schemas import StatusResponse
from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import business_metrics
from querylens.schema.catalog import CatalogService
from querylens.semantics.metrics import MetricDefinition, MetricDSL
from querylens.semantics.versions import (
    advance_semantic_version,
    check_metric_aliases,
    lock_semantic_connection,
    visible_metrics,
)

router = APIRouter(prefix="/connections/{connection_id}/metrics", tags=["metrics"])


class MetricResponse(MetricDefinition):
    pass


class UpdateMetricRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expected_version: int = Field(ge=1)
    dsl: MetricDSL | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def has_change(self):
        if not self.model_fields_set & {"dsl", "enabled"} or any(
            getattr(self, field) is None for field in self.model_fields_set & {"dsl", "enabled"}
        ):
            raise ValueError("Provide a non-null dsl or enabled change")
        return self


def validate_dsl(dsl: MetricDSL, snapshot) -> None:
    try:
        dsl.validate_against_snapshot(snapshot)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


@router.post("", response_model=MetricResponse, status_code=status.HTTP_201_CREATED)
def create_metric(
    connection_id: str,
    payload: MetricDSL,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> MetricResponse:
    user_id = current_user["user_id"]
    snapshot = CatalogService().get_catalog(user_id, connection_id)
    metric_id = str(uuid.uuid4())
    now = dt.datetime.now(dt.timezone.utc)
    try:
        with get_db_connection() as conn:
            lock_semantic_connection(conn, user_id, snapshot)
            validate_dsl(payload, snapshot)
            check_metric_aliases(conn, connection_id, payload)
            conn.execute(
                business_metrics.insert().values(
                    id=metric_id,
                    connection_id=connection_id,
                    key=payload.key,
                    name=payload.name,
                    description=payload.description,
                    dsl_json=payload.model_dump_json(),
                    version=1,
                    enabled=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            advance_semantic_version(conn, connection_id)
    except sa.exc.IntegrityError as exc:
        raise HTTPException(409, "Metric key already exists for this connection") from exc
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
def list_metrics(connection_id: str, current_user: dict[str, Any] = Depends(get_current_user)) -> list[MetricResponse]:
    user_id = current_user["user_id"]
    snapshot = CatalogService().get_catalog(user_id, connection_id)
    with get_db_connection() as conn:
        lock_semantic_connection(conn, user_id, snapshot, read=True)
        return [MetricResponse(**metric.model_dump()) for metric in visible_metrics(conn, snapshot)]


@router.patch("/{metric_id}", response_model=MetricResponse)
def update_metric(
    connection_id: str,
    metric_id: str,
    payload: UpdateMetricRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> MetricResponse:
    user_id = current_user["user_id"]
    snapshot = CatalogService().get_catalog(user_id, connection_id)
    try:
        with get_db_connection() as conn:
            lock_semantic_connection(conn, user_id, snapshot)
            old = next((m for m in visible_metrics(conn, snapshot) if m.id == metric_id), None)
            if old is None:
                raise NotFoundError("Metric not found")
            if old.version != payload.expected_version:
                raise HTTPException(409, "Metric changed; reload before saving")
            dsl = payload.dsl if payload.dsl is not None else old.dsl
            enabled = old.enabled if payload.enabled is None else payload.enabled
            validate_dsl(dsl, snapshot)
            if enabled:
                check_metric_aliases(conn, connection_id, dsl, exclude_id=metric_id)
            changed = dsl != old.dsl or enabled != old.enabled
            version = old.version + int(changed)
            if changed:
                conn.execute(
                    business_metrics.update()
                    .where(business_metrics.c.id == metric_id)
                    .values(
                        key=dsl.key,
                        name=dsl.name,
                        description=dsl.description,
                        dsl_json=dsl.model_dump_json(),
                        version=version,
                        enabled=enabled,
                        updated_at=dt.datetime.now(dt.timezone.utc),
                    )
                )
                advance_semantic_version(conn, connection_id)
            return MetricResponse(
                id=metric_id,
                connection_id=connection_id,
                key=dsl.key,
                name=dsl.name,
                description=dsl.description,
                dsl=dsl,
                version=version,
                enabled=enabled,
            )
    except sa.exc.IntegrityError as exc:
        raise HTTPException(409, "Metric key already exists for this connection") from exc


@router.delete("/{metric_id}", response_model=StatusResponse)
def delete_metric(
    connection_id: str,
    metric_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> StatusResponse:
    user_id = current_user["user_id"]
    snapshot = CatalogService().get_catalog(user_id, connection_id)
    with get_db_connection() as conn:
        lock_semantic_connection(conn, user_id, snapshot)
        # Deletes are owner-scoped even when a definition's target has since been hidden.
        result = conn.execute(
            business_metrics.delete().where(
                business_metrics.c.id == metric_id, business_metrics.c.connection_id == connection_id
            )
        )
        if not result.rowcount:
            raise NotFoundError("Metric not found")
        advance_semantic_version(conn, connection_id)
    return StatusResponse(status="deleted")
