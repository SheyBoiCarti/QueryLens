"""Query trace API and diagnostics retrieval (Contracts C02, C08, C09, C11)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from querylens.auth.dependencies import get_current_user
from querylens.auth.ownership import verify_query_run_ownership
from querylens.persistence.repositories.query_runs import QueryRunRepository

router = APIRouter(prefix="/queries", tags=["traces"])


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AttemptTraceItem(StrictBaseModel):
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
    attempts: list[AttemptTraceItem]


def get_trace(user_id: str, query_id: str) -> dict[str, Any]:
    """Retrieve trace for a query run, enforcing ownership (Contract C02)."""
    verify_query_run_ownership(query_id, user_id)
    repo = QueryRunRepository()
    run = repo.get(query_id, user_id=user_id)
    raw_attempts = repo.get_attempts(query_id)

    attempts = [
        {
            "attempt_number": a["attempt_number"],
            "status": a["status"],
            "generated_sql": a["generated_sql"],
            "prompt_tokens": a["prompt_tokens"],
            "completion_tokens": a["completion_tokens"],
            "latency_ms": a["latency_ms"],
            "error_signature": a["error_signature"],
        }
        for a in raw_attempts
    ]
    return {
        "query_id": query_id,
        "status": run["status"],
        "attempts": attempts,
    }


@router.get("/{query_id}/trace", response_model=QueryTraceResponse)
def get_query_trace_endpoint(
    query_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
) -> QueryTraceResponse:
    user_id = current_user["user_id"]
    trace_data = get_trace(user_id, query_id)
    return QueryTraceResponse(**trace_data)
