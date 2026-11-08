"""Owner-bound query history and run deletion API (Contracts C02, C05, C09)."""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict

from querylens.auth.dependencies import get_current_user, verify_csrf_token
from querylens.auth.ownership import verify_query_run_ownership
from querylens.jobs.results import get_result_cache
from querylens.persistence.repositories.history import HistoryRepository
from querylens.schema.snapshots import get_latest_snapshot

router = APIRouter(prefix="/queries", tags=["history"])


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class HistoryItem(StrictBaseModel):
    id: str
    connection_id: str
    question: str
    status: str
    created_at: str
    max_rows: int
    results_available: bool


class HistoryResponse(StrictBaseModel):
    items: list[HistoryItem]
    next_cursor: str | None = None


@router.get("/history", response_model=HistoryResponse)
def get_query_history(
    cursor: str | None = Query(None, description="Keyset pagination cursor"),
    limit: int = Query(20, ge=1, le=100, description="Items per page (max 100)"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> HistoryResponse:
    """Retrieve owner-filtered query history with stable keyset pagination (Contract C09)."""
    user_id = current_user["user_id"]
    repo = HistoryRepository()
    cache = get_result_cache()

    raw_items, next_cursor = repo.list_user_runs(user_id=user_id, cursor=cursor, limit=limit)

    items = []
    for r in raw_items:
        snapshot = get_latest_snapshot(r["connection_id"])
        is_available = snapshot is not None and cache.get(r["id"], snapshot.snapshot_hash) is not None
        items.append(
            HistoryItem(
                id=r["id"],
                connection_id=r["connection_id"],
                question=r["question"],
                status=r["status"],
                created_at=r["created_at"].isoformat()
                if hasattr(r["created_at"], "isoformat")
                else str(r["created_at"]),
                max_rows=r["max_rows"],
                results_available=is_available,
            )
        )

    return HistoryResponse(items=items, next_cursor=next_cursor)


@router.delete("/{query_id}")
async def delete_query(
    query_id: str,
    current_user: dict[str, Any] = Depends(get_current_user),
    _csrf: None = Depends(verify_csrf_token),
) -> dict[str, str]:
    """Delete a query run and cascade-evict associated attempts and cached rows (Contracts C02, C09)."""
    user_id = current_user["user_id"]
    verify_query_run_ownership(query_id, user_id)

    repo = HistoryRepository()
    from querylens.jobs.cancel import request_cancel

    await request_cancel(query_id, user_id)
    from querylens.utils.workers import run_db

    await run_db(repo.delete_run, query_id, user_id)

    cache = get_result_cache()
    cache.evict(query_id)

    return {"status": "deleted", "query_id": query_id}
