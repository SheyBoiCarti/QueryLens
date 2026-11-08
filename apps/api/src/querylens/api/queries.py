"""Public Query Execution API endpoints (Contracts C02, C07, C08, C09)."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from typing import Any
from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, ConfigDict, Field

from querylens.api.query_schemas import ParameterDiscoveryResponse, PublicRun
from querylens.domain.analytics import RunContext
from querylens.pipeline.explanation import derive_presentation
from querylens.schema.catalog import CatalogService
from querylens.semantics.versions import label_is_visible, load_semantic_context
from querylens.sql.parameters import extract_eligible_parameters
from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.auth.ownership import verify_connection_ownership
from querylens.jobs.results import get_result_cache
from querylens.jobs.admission import get_admission_controller
from querylens.utils.workers import run_db
from querylens.config import get_settings
from fastapi import HTTPException
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.pipeline.orchestrator import register_active_task, run_query_pipeline
from querylens.domain.schema import CatalogSnapshot
from querylens.schema.snapshots import get_latest_snapshot

router = APIRouter(prefix="/queries", tags=["queries"])


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateQueryRequest(StrictBaseModel):
    connection_id: str
    question: str = Field(..., min_length=1, max_length=4000)
    max_rows: int = Field(default=100, ge=1, le=1000)
    parent_query_id: str | None = None


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
    await run_db(verify_connection_ownership, payload.connection_id, user_id)
    settings = get_settings()
    if len(payload.question) > settings.max_question_chars or payload.max_rows > settings.max_max_rows:
        raise HTTPException(422, "Question or row limit exceeds configured budget")

    origin: str = "natural_language"
    if payload.parent_query_id:
        parent = await run_db(QueryRunRepository().get, payload.parent_query_id, user_id=user_id)
        if parent is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent query not found")
        if parent.get("user_id") != user_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Parent query not found")
        if parent.get("connection_id") != payload.connection_id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Parent query belongs to a different connection")
        if parent.get("status") != "completed":
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Parent query must be completed, but is '{parent.get('status')}'",
            )

        from querylens.pipeline.followup import (
            FollowUpContextOversized,
            FollowUpContextStale,
            resolve_followup_context,
        )

        snapshot = await run_db(CatalogService().get_catalog, user_id, payload.connection_id)
        semantics = await run_db(load_semantic_context, user_id, snapshot)
        try:
            await run_db(
                resolve_followup_context,
                payload.parent_query_id,
                user_id,
                payload.connection_id,
                snapshot,
                semantics,
                payload.question,
            )
        except FollowUpContextStale as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"error_code": "FOLLOWUP_CONTEXT_STALE", "message": str(exc)},
            )
        except FollowUpContextOversized as exc:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail={"error_code": "FOLLOWUP_CONTEXT_OVERSIZED", "message": str(exc)},
            )
        origin = "follow_up"

    reservation = get_admission_controller().reserve(user_id, payload.connection_id)

    query_id = str(uuid.uuid4())
    repo = QueryRunRepository()
    try:
        await run_db(
            repo.create,
            query_id=query_id,
            user_id=user_id,
            connection_id=payload.connection_id,
            question=payload.question,
            max_rows=payload.max_rows,
            origin=origin,
            parent_query_id=payload.parent_query_id,
        )
        task = asyncio.create_task(
            run_query_pipeline(
                query_id=query_id,
                user_id=user_id,
                connection_id=payload.connection_id,
                question=payload.question,
                max_rows=payload.max_rows,
                reservation=reservation,
                parent_query_id=payload.parent_query_id,
            )
        )
        task.add_done_callback(lambda _: reservation.release())
        register_active_task(query_id, task)
    except BaseException:
        reservation.release()
        raise

    return CreateQueryResponse(query_id=query_id, status="queued")


@router.get("/{query_id}", response_model=PublicRun, response_model_exclude_none=True)
def get_query(
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
        "origin": run.get("origin") or "natural_language",
        **{
            key: run.get(key)
            for key in ("parent_query_id", "source_query_id", "saved_question_id", "saved_question_version")
        },
        "state_version": run["state_version"],
        "question": run["question"],
        "created_at": run["created_at"].isoformat()
        if hasattr(run["created_at"], "isoformat")
        else str(run["created_at"]),
        "updated_at": run["updated_at"].isoformat()
        if hasattr(run["updated_at"], "isoformat")
        else str(run["updated_at"]),
    }

    if status_val == "completed":
        # Get attempts for generated SQL
        attempts = repo.get_attempts(query_id)
        last_sql = run.get("canonical_sql") or (attempts[-1]["generated_sql"] if attempts else "")

        # Fetch cached rows
        connection = verify_connection_ownership(run["connection_id"], user_id)
        catalog = get_latest_snapshot(run["connection_id"])
        current_catalog = catalog is not None and catalog.policy_version == connection["policy_version"]
        cache = get_result_cache()
        if not current_catalog:
            # Delivery never needs credentials or source reflection. Revoked/stale
            # snapshots cannot authorize rows or historical semantic copies.
            cache.evict(query_id)
            catalog = CatalogSnapshot(
                connection_id=run["connection_id"],
                engine=connection["engine"],
                policy_version=connection["policy_version"],
            )
        assert catalog is not None
        entry = cache.get_entry(query_id, catalog.snapshot_hash) if current_catalog else None
        context = None
        semantics = None
        if run.get("run_context_json"):
            stored = RunContext.model_validate_json(run["run_context_json"])
            semantics = load_semantic_context(user_id, catalog) if current_catalog else None
            visible_metrics = {m.id: m for m in semantics.metrics} if semantics else {}
            metric_refs = tuple(
                r
                for r in stored.metric_references
                if r.id in visible_metrics
                and visible_metrics[r.id].version == r.version
                and visible_metrics[r.id].dsl.compute_hash() == r.dsl_hash
            )
            context = stored.model_copy(
                update={
                    "label_references": tuple(
                        label for label in stored.label_references if label_is_visible(label, catalog)
                    ),
                    "metric_references": metric_refs,
                    "effective_question": stored.effective_question
                    if len(metric_refs) == len(stored.metric_references)
                    else "Query result from the validated SQL; see the canonical template and filters for scope.",
                }
            )
            base_response["context"] = context

        cached = (entry.columns, entry.rows) if entry is not None else None

        if cached is not None:
            assert entry is not None
            cols, rows = cached
            base_response["results_expires_at"] = entry.results_expires_at.isoformat()
            if context is not None:
                base_response["presentation"] = derive_presentation(
                    cols,
                    rows,
                    context,
                    base_response["origin"],
                    bool(run.get("truncated")),
                    semantics=semantics,
                )
            base_response.update(
                {
                    "dialect": catalog.engine,
                    "sql": last_sql,
                    "assumptions": json.loads(run.get("assumptions") or "[]"),
                    "warnings": json.loads(run.get("warnings") or "[]"),
                    "columns": cols,
                    "row_count": len(rows),
                    "truncated": bool(run.get("truncated")),
                    "results_available": True,
                    "rows": rows,
                }
            )
        else:
            base_response.update(
                {
                    "dialect": catalog.engine,
                    "sql": last_sql,
                    "assumptions": json.loads(run.get("assumptions") or "[]"),
                    "warnings": json.loads(run.get("warnings") or "[]"),
                    "columns": [],
                    "row_count": 0,
                    "truncated": False,
                    "results_available": False,
                }
            )

    elif status_val == "clarification_required":
        base_response["clarification_question"] = run.get("clarification_question") or "Clarification required"

    elif status_val in ("failed", "rejected", "interrupted"):
        base_response.update(
            {
                "error_code": run.get("error_code") or "ERROR",
                "safe_message": run.get("safe_message") or "An error occurred",
            }
        )

    elif status_val == "cancelled":
        base_response["safe_message"] = run.get("safe_message") or "Query cancelled by user"

    return base_response


@router.get("/{query_id}/trace", response_model=QueryTraceResponse)
def get_query_trace(
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


@router.get("/{query_id}/parameters", response_model=ParameterDiscoveryResponse)
def get_query_parameters(
    query_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> ParameterDiscoveryResponse:
    """Discover eligible filter parameters from a completed query run."""
    user_id = current_user["user_id"]
    repo = QueryRunRepository()
    run = repo.get(query_id, user_id=user_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Query not found")
    if run["status"] != "completed":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Query must be completed to extract parameters")

    verify_connection_ownership(run["connection_id"], user_id)
    snapshot = CatalogService().get_catalog(user_id, run["connection_id"])

    template_sql = run.get("canonical_sql") or ""
    author_limit = None
    if run.get("run_context_json"):
        try:
            ctx = json.loads(run["run_context_json"])
            template_sql = ctx.get("canonical_sql_template") or template_sql
            author_limit = ctx.get("author_limit")
        except Exception:
            pass

    definitions = extract_eligible_parameters(
        template_sql,
        snapshot,
        snapshot.engine,
        author_limit,
        default_max_rows=run.get("max_rows", 100),
    )
    template_fingerprint = hashlib.sha256(template_sql.strip().encode("utf-8")).hexdigest()

    return ParameterDiscoveryResponse(
        template_fingerprint=template_fingerprint,
        definitions=definitions,
    )


@router.post("/{query_id}/cancel")
async def cancel_query(
    query_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> dict[str, str]:
    """Idempotently cancel an active query run."""
    from querylens.jobs.cancel import request_cancel

    user_id = current_user["user_id"]
    return await request_cancel(query_id, user_id)


class CreateSQLQueryRequest(StrictBaseModel):
    connection_id: str
    sql: str = Field(min_length=1, max_length=32768)
    source_query_id: str | None = None
    max_rows: int = Field(default=100, ge=1, le=1000, strict=True)


@router.post("/sql", response_model=CreateQueryResponse, status_code=status.HTTP_202_ACCEPTED)
async def create_sql_query(
    payload: CreateSQLQueryRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> CreateQueryResponse:
    """Submit an independent edited SQL run through the read-only execution policy."""
    from querylens.pipeline.direct import authorize_manual_source, run_manual_sql_pipeline

    user_id = current_user["user_id"]
    await run_db(verify_connection_ownership, payload.connection_id, user_id)
    await run_db(authorize_manual_source, payload.source_query_id, user_id, payload.connection_id)
    settings = get_settings()
    if payload.max_rows > settings.max_max_rows or len(payload.sql.encode("utf-8")) > settings.max_sql_bytes:
        raise HTTPException(422, "SQL or row limit exceeds configured budget")
    reservation = get_admission_controller().reserve(user_id, payload.connection_id)
    query_id = str(uuid.uuid4())
    repo = QueryRunRepository()
    try:
        await run_db(
            repo.create,
            query_id=query_id,
            user_id=user_id,
            connection_id=payload.connection_id,
            question="Edited SQL",
            max_rows=payload.max_rows,
            origin="manual_sql",
            source_query_id=payload.source_query_id,
            submitted_sql=payload.sql,
        )
        task = asyncio.create_task(
            run_manual_sql_pipeline(
                query_id=query_id,
                user_id=user_id,
                connection_id=payload.connection_id,
                sql=payload.sql,
                source_query_id=payload.source_query_id,
                max_rows=payload.max_rows,
                reservation=reservation,
            )
        )
        task.add_done_callback(lambda _: reservation.release())
        register_active_task(query_id, task)
    except BaseException:
        reservation.release()
        raise
    return CreateQueryResponse(query_id=query_id)
