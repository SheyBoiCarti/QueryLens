"""Bounded CSV export API endpoints (Contracts C02, C07, C09)."""

from __future__ import annotations

import re
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status

from querylens.auth.dependencies import get_current_user
from querylens.auth.ownership import verify_query_run_ownership, verify_connection_ownership
from querylens.export.csv import ResultTooLargeError, generate_csv_string
from querylens.jobs.results import get_result_cache
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.schema.snapshots import get_latest_snapshot

router = APIRouter(prefix="/queries", tags=["exports"])


@router.get("/{query_id}/export")
def export_query_results(
    query_id: str,
    format: str = Query("csv", description="Target export format"),
    current_user: dict[str, Any] = Depends(get_current_user),
) -> Response:
    """Stream bounded, sanitized CSV results from volatile memory (Contract C09)."""
    # 1. Validate format
    if format.lower() != "csv":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Unsupported export format '{format}'. Only 'csv' is supported.",
        )

    user_id = current_user["user_id"]

    # 2. Authorize run ownership first; returns 404 if unknown or foreign (Contract C02)
    verify_query_run_ownership(query_id, user_id)

    # 3. Retrieve from volatile cache
    cache = get_result_cache()
    run = QueryRunRepository().get(query_id, user_id=user_id)
    connection = verify_connection_ownership(run["connection_id"], user_id)
    catalog = get_latest_snapshot(run["connection_id"])
    if catalog is None or catalog.policy_version != connection["policy_version"]:
        cache.evict(query_id)
        cached = None
    else:
        cached = cache.get(query_id, catalog.snapshot_hash)

    # 4. If cache has expired / been evicted, return 410 Gone (Contract C09)
    if cached is None:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail="Cached results have expired or been evicted. Submit query again to view results.",
        )

    columns, rows = cached

    # 5. Format CSV with formula injection neutralization and byte bounds
    try:
        csv_content = generate_csv_string(columns, rows)
    except ResultTooLargeError as e:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(e),
        )

    # 6. Sanitize filename (valid UUID or slug only)
    safe_filename = re.sub(r"[^a-zA-Z0-9_-]", "", query_id)

    headers = {
        "Content-Type": "text/csv; charset=utf-8",
        "Content-Disposition": f'attachment; filename="{safe_filename}.csv"',
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    }

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers=headers,
    )
