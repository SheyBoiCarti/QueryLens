"""Public Query Execution API endpoints (Contracts C02, C07, C08, C09)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any
from fastapi import APIRouter, Depends, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field

from querylens.api.errors import NotFoundError
from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.auth.ownership import verify_connection_ownership, verify_query_run_ownership
from querylens.jobs.results import get_result_cache
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.pipeline.orchestrator import cancel_active_task, register_active_task, run_query_pipeline
from querylens.schema.catalog import CatalogService

router = APIRouter(prefix="/queries", tags=["queries"])


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateQueryRequest(StrictBaseModel):
    connection_id: str
    question: str = Field(..., min_length=1, max_length=4000)
    max_rows: int = Field(default=100, ge=1, le=1000)


class CreateQueryResponse(StrictBaseModel):
    query_id: str
    status: str = "queued"


class QueryAttemptResponse(StrictBaseModel):
    attempt_number: int
    status: str
    generated_sql: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    error_signature: str | None = None


class QueryTraceResponse(StrictBaseModel):
    query_id: str
    status: str
    attempts: list[QueryAttemptResponse]


@router.post("", response_model=CreateQueryResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_query(
    payload: CreateQueryRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> CreateQueryResponse:
    """Submit a natural-language analytics question for asynchronous processing."""
    user_id = current_user["user_id"]
    # Authorize connection ownership before queueing (Contract C02)
    verify_connection_ownership(payload.connection_id, user_id)

    query_id = str(uuid.uuid4())
    repo = QueryRunRepository()
    repo.create(
        query_id=query_id,
        user_id=user_id,
        connection_id=payload.connection_id,
        question=payload.question,
        max_rows=payload.max_rows,
    )

    # Spawn async pipeline task
    task = asyncio.create_task(
        run_query_pipeline(
            query_id=query_id,
            user_id=user_id,
            connection_id=payload.connection_id,
            question=payload.question,
            max_rows=payload.max_rows,
        )
    )
    register_active_task(query_id, task)

    return CreateQueryResponse(query_id=query_id, status="queued")


@router.get("/{query_id}")
async def get_query(
    query_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> dict[str, Any]:
    """Retrieve query status, generated SQL, bounded results, or actionable clarification (Contract C08)."""
    user_id = current_user["user_id"]
    repo = QueryRunRepository()
    run = repo.get(query_id, user_id=user_id)

    status_val = run["status"]
    base_response = {
        "query_id": run["id"],
        "connection_id": run["connection_id"],
        "status": status_val,
        "state_version": run["state_version"],
        "question": run["question"],
        "created_at": run["created_at"].isoformat() if hasattr(run["created_at"], "isoformat") else str(run["created_at"]),
        "updated_at": run["updated_at"].isoformat() if hasattr(run["updated_at"], "isoformat") else str(run["updated_at"]),
    }

    if status_val == "completed":
        # Get attempts for generated SQL
        attempts = repo.get_attempts(query_id)
        last_sql = attempts[-1]["generated_sql"] if attempts else ""

        # Fetch cached rows
        catalog = CatalogService().get_catalog(user_id, run["connection_id"])
        cache = get_result_cache()
        cached = cache.get(query_id, catalog.snapshot_hash)

        if cached is not None:
            cols, rows = cached
            base_response.update({
                "dialect": catalog.engine,
                "sql": last_sql,
                "assumptions": [],
                "warnings": [],
                "columns": cols,
                "row_count": len(rows),
                "truncated": len(rows) >= run["max_rows"],
                "results_available": True,
                "rows": rows,
            })
        else:
            base_response.update({
                "dialect": catalog.engine,
                "sql": last_sql,
                "assumptions": [],
                "warnings": [],
                "columns": [],
                "row_count": 0,
                "truncated": False,
                "results_available": False,
            })

    elif status_val == "clarification_required":
        base_response["clarification_question"] = run.get("clarification_question") or "Clarification required"

    elif status_val in ("failed", "rejected", "interrupted"):
        base_response.update({
            "error_code": run.get("error_code") or "ERROR",
            "safe_message": run.get("safe_message") or "An error occurred",
        })

    elif status_val == "cancelled":
        base_response["safe_message"] = run.get("safe_message") or "Query cancelled by user"

    return base_response


@router.get("/{query_id}/trace", response_model=QueryTraceResponse)
async def get_query_trace(
    query_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> QueryTraceResponse:
    """Retrieve execution attempt trace."""
    user_id = current_user["user_id"]
    repo = QueryRunRepository()
    run = repo.get(query_id, user_id=user_id)
    raw_attempts = repo.get_attempts(query_id)

    attempts = [
        QueryAttemptResponse(
            attempt_number=a["attempt_number"],
            status=a["status"],
            generated_sql=a["generated_sql"],
            prompt_tokens=a["prompt_tokens"],
            completion_tokens=a["completion_tokens"],
            latency_ms=a["latency_ms"],
            error_signature=a["error_signature"],
        )
        for a in raw_attempts
    ]

    return QueryTraceResponse(
        query_id=query_id,
        status=run["status"],
        attempts=attempts,
    )


@router.post("/{query_id}/cancel")
async def cancel_query(
    query_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> dict[str, str]:
    """Idempotently cancel an active query run."""
    user_id = current_user["user_id"]
    repo = QueryRunRepository()
    run = repo.get(query_id, user_id=user_id)

    if run["status"] not in ("completed", "failed", "rejected", "clarification_required", "cancelled", "interrupted"):
        cancel_active_task(query_id)
        repo.update_state(query_id, "cancelled", safe_message="Query was cancelled by user")

    return {"query_id": query_id, "status": "cancelled"}
