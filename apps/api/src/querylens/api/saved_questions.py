"""API endpoints for saved questions, revisions, and direct reruns (Contract C09)."""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import uuid
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, status

from querylens.api.queries import CreateQueryResponse
from querylens.api.query_schemas import (
    SavedQuestionCreateRequest,
    SavedQuestionDetail,
    SavedQuestionDuplicateRequest,
    SavedQuestionListResponse,
    SavedQuestionRunRequest,
    SavedQuestionSummary,
    SavedQuestionUpdateRequest,
)
from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.auth.ownership import verify_connection_ownership
from querylens.jobs.admission import get_admission_controller
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.persistence.repositories.saved_questions import SavedQuestionRepository
from querylens.pipeline.direct import run_saved_question_pipeline
from querylens.pipeline.orchestrator import register_active_task
from querylens.schema.catalog import CatalogService
from querylens.semantics.saved_questions import (
    SavedQuestionReviewRequired,
    validate_saved_dependencies,
)
from querylens.semantics.versions import load_semantic_context
from querylens.sql.parameters import (
    ParameterCompilationError,
    ParameterDefinition,
    extract_eligible_parameters,
    verify_parameter_definitions,
)

router = APIRouter(prefix="/saved-questions", tags=["saved_questions"])


def _format_summary(saved: dict[str, Any]) -> SavedQuestionSummary:
    created_at = saved["created_at"]
    updated_at = saved["updated_at"]
    return SavedQuestionSummary(
        id=saved["id"],
        connection_id=saved["connection_id"],
        title=saved["title"],
        description=saved.get("description"),
        chart_preference=saved.get("chart_preference"),
        default_max_rows=saved.get("default_max_rows", 100),
        revision=saved.get("revision", 1),
        created_at=created_at.isoformat() if hasattr(created_at, "isoformat") else str(created_at),
        updated_at=updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
    )


def _format_detail(saved: dict[str, Any]) -> SavedQuestionDetail:
    raw_defs = json.loads(saved.get("parameter_definitions_json") or "[]")
    return SavedQuestionDetail(
        **_format_summary(saved).model_dump(),
        canonical_sql_template=saved["canonical_sql_template"],
        effective_question=saved["effective_question"],
        parameters=[ParameterDefinition.model_validate(d) for d in raw_defs],
        referenced_objects=json.loads(saved.get("referenced_objects_json") or "[]"),
        metric_references=json.loads(saved.get("metric_references_json") or "[]"),
    )


def _definition_from_run(run: dict[str, Any]) -> dict[str, Any]:
    """Copy completed-run provenance, retaining fallbacks for legacy runs."""
    context: dict[str, Any] = {}
    if run.get("run_context_json"):
        try:
            context = json.loads(run["run_context_json"])
        except Exception:
            pass

    return {
        "canonical_sql_template": context.get("canonical_sql_template") or run.get("canonical_sql") or "",
        "effective_question": context.get("effective_question") or run.get("question") or "",
        "referenced_objects_json": json.dumps(context.get("referenced_objects") or []),
        "metric_references_json": json.dumps(context.get("metric_references") or []),
        "label_references_json": json.dumps(context.get("label_references") or []),
        "snapshot_hash": context.get("snapshot_hash") or run.get("snapshot_hash") or "",
        "policy_version": context.get("policy_version") or run.get("policy_version") or 1,
        "semantic_version": context.get("semantic_version") or 1,
        "author_limit": context.get("author_limit"),
        "default_max_rows": run.get("max_rows", 100),
    }


@router.post("", response_model=SavedQuestionDetail, status_code=status.HTTP_201_CREATED)
def create_saved_question(
    payload: SavedQuestionCreateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> SavedQuestionDetail:
    """Create a saved question from an authorized completed source query run."""
    user_id = current_user["user_id"]
    query_repo = QueryRunRepository()
    run = query_repo.get(payload.source_query_id, user_id=user_id)
    if run is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source query not found")
    if run["status"] != "completed":
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Source query must be completed")

    verify_connection_ownership(run["connection_id"], user_id)

    definition = _definition_from_run(run)
    snapshot = CatalogService().get_catalog(user_id, run["connection_id"])
    discovered = extract_eligible_parameters(
        definition["canonical_sql_template"], snapshot, snapshot.engine, definition["author_limit"],
        default_max_rows=int(definition["default_max_rows"]),
    )
    try:
        verify_parameter_definitions(tuple(payload.parameters), discovered)
    except ParameterCompilationError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc

    param_defs_json = json.dumps([p.model_dump() for p in payload.parameters])
    param_defaults_json = json.dumps({p.name: p.default_value for p in payload.parameters if p.default_value is not None})

    record_id = str(uuid.uuid4())
    now = dt.datetime.now(dt.timezone.utc)
    record = {
        "id": record_id,
        "connection_id": run["connection_id"],
        "user_id": user_id,
        "title": payload.title,
        "description": payload.description,
        **definition,
        "parameter_definitions_json": param_defs_json,
        "parameter_defaults_json": param_defaults_json,
        "chart_preference": payload.chart_preference,
        "revision": 1,
        "created_at": now,
        "updated_at": now,
    }

    saved = SavedQuestionRepository().create(record)
    return _format_detail(saved)


@router.get("", response_model=SavedQuestionListResponse)
def list_saved_questions(
    connection_id: str,
    search: str | None = None,
    cursor: str | None = None,
    limit: int = Query(default=20, ge=1, le=100),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SavedQuestionListResponse:
    """List saved questions for a connection with optional search and cursor pagination."""
    user_id = current_user["user_id"]
    verify_connection_ownership(connection_id, user_id)

    items, next_cursor = SavedQuestionRepository().list_for_connection(
        connection_id=connection_id,
        user_id=user_id,
        search=search,
        cursor=cursor,
        limit=limit,
    )

    return SavedQuestionListResponse(items=[_format_summary(item) for item in items], next_cursor=next_cursor)


@router.get("/{saved_question_id}", response_model=SavedQuestionDetail)
def get_saved_question(
    saved_question_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> SavedQuestionDetail:
    """Get full details of a saved question."""
    user_id = current_user["user_id"]
    saved = SavedQuestionRepository().get(saved_question_id, user_id)
    if saved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved question not found")
    return _format_detail(saved)


@router.patch("/{saved_question_id}", response_model=SavedQuestionDetail)
def update_saved_question(
    saved_question_id: str,
    payload: SavedQuestionUpdateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> SavedQuestionDetail:
    """Optimistically update saved question metadata or replace with a new successful run."""
    user_id = current_user["user_id"]
    repo = SavedQuestionRepository()
    existing = repo.get(saved_question_id, user_id)
    if existing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved question not found")

    changes: dict[str, Any] = {}
    if payload.title is not None:
        changes["title"] = payload.title
    if "description" in payload.model_fields_set:
        changes["description"] = payload.description
    if "chart_preference" in payload.model_fields_set:
        changes["chart_preference"] = payload.chart_preference
    if payload.replacement_query_id is not None:
        query_repo = QueryRunRepository()
        run = query_repo.get(payload.replacement_query_id, user_id=user_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Replacement query not found")
        if run["status"] != "completed" or run["connection_id"] != existing["connection_id"]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Replacement must be a completed run on same connection")

        changes.update(_definition_from_run(run))

    if payload.parameters is not None or payload.replacement_query_id is not None:
        snapshot = CatalogService().get_catalog(user_id, existing["connection_id"])
        template = changes.get("canonical_sql_template", existing["canonical_sql_template"])
        discovered = extract_eligible_parameters(
            template, snapshot, snapshot.engine,
            changes.get("author_limit", existing.get("author_limit")),
            int(changes.get("default_max_rows", existing.get("default_max_rows", 100))),
        )
        definitions = tuple(payload.parameters) if payload.parameters is not None else tuple(discovered)
        try:
            verify_parameter_definitions(definitions, discovered)
        except ParameterCompilationError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
        changes["parameter_definitions_json"] = json.dumps([p.model_dump() for p in definitions])
        changes["parameter_defaults_json"] = json.dumps({p.name: p.default_value for p in definitions})

    updated = repo.update(saved_question_id, user_id, payload.expected_revision, changes)
    if updated is None:
        latest = repo.get(saved_question_id, user_id)
        if latest is not None and latest["revision"] != payload.expected_revision:
            raise HTTPException(status.HTTP_409_CONFLICT, "Saved question revision conflict; reload and retry")
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved question not found")

    return _format_detail(updated)


@router.post("/{saved_question_id}/duplicate", response_model=SavedQuestionDetail, status_code=status.HTTP_201_CREATED)
def duplicate_saved_question(
    saved_question_id: str,
    payload: SavedQuestionDuplicateRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> SavedQuestionDetail:
    """Duplicate an existing saved question as an independent revision-1 definition."""
    user_id = current_user["user_id"]
    repo = SavedQuestionRepository()
    source = repo.get(saved_question_id, user_id)
    if source is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Source saved question not found")

    new_record = dict(source)
    new_record["id"] = str(uuid.uuid4())
    new_record["title"] = payload.title
    new_record["revision"] = 1
    now = dt.datetime.now(dt.timezone.utc)
    new_record["created_at"] = now
    new_record["updated_at"] = now

    created = repo.create(new_record)
    return _format_detail(created)


@router.delete("/{saved_question_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_saved_question(
    saved_question_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> None:
    """Delete a saved question definition."""
    user_id = current_user["user_id"]
    deleted = SavedQuestionRepository().delete(saved_question_id, user_id)
    if not deleted:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved question not found")


@router.post("/{saved_question_id}/run", response_model=CreateQueryResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_saved_question(
    saved_question_id: str,
    payload: SavedQuestionRunRequest,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> CreateQueryResponse:
    """Execute a saved question directly with supplied or default parameter values."""
    user_id = current_user["user_id"]
    saved = SavedQuestionRepository().get(saved_question_id, user_id)
    if saved is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Saved question not found")

    if payload.expected_revision != saved["revision"]:
        raise HTTPException(status.HTTP_409_CONFLICT, "Saved question revision conflict; reload and retry")

    raw_defs = json.loads(saved.get("parameter_definitions_json") or "[]")
    allowed_names = {item["name"] for item in raw_defs}
    unknown = set(payload.parameters) - allowed_names
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown saved question parameter")

    verify_connection_ownership(saved["connection_id"], user_id)
    snapshot = CatalogService().get_catalog(user_id, saved["connection_id"])
    semantics = load_semantic_context(user_id, snapshot)

    try:
        validate_saved_dependencies(saved, snapshot, semantics)
    except SavedQuestionReviewRequired as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={"error_code": "SAVED_QUESTION_REVIEW_REQUIRED", "message": exc.message},
        )

    # Resolve and validate values before accepting work. The worker repeats
    # compilation against its current snapshot immediately before execution.
    from querylens.sql.parameters import ParameterDefinition, compile_parameterized_query
    try:
        definitions = tuple(ParameterDefinition.model_validate(item) for item in raw_defs)
        compile_parameterized_query(
            saved["canonical_sql_template"], definitions, payload.parameters, snapshot,
            saved["connection_id"], snapshot.engine, int(saved.get("default_max_rows") or 100),
            saved.get("author_limit"), dt.datetime.now(dt.timezone.utc),
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid saved question parameters") from exc

    query_id = str(uuid.uuid4())
    admission = get_admission_controller()
    reservation = admission.reserve(user_id, saved["connection_id"])

    try:
        QueryRunRepository().create(
            query_id=query_id,
            user_id=user_id,
            connection_id=saved["connection_id"],
            question=saved["effective_question"],
            max_rows=saved.get("default_max_rows", 100),
            origin="saved_question",
            saved_question_id=saved["id"],
            saved_question_version=saved["revision"],
            saved_definition_json=json.dumps(saved, default=str),
        )
    except Exception:
        reservation.release()
        raise

    task = asyncio.create_task(
        run_saved_question_pipeline(
            query_id=query_id,
            user_id=user_id,
            connection_id=saved["connection_id"],
            saved_definition=saved,
            supplied_values=payload.parameters,
            reservation=reservation,
        )
    )
    register_active_task(query_id, task)

    return CreateQueryResponse(query_id=query_id, status="queued")
