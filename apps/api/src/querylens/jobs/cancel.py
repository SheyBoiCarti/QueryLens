"""Query cancellation coordinator across tasks and active source databases (Contracts C02, C07, C08)."""

from __future__ import annotations

from typing import Any

from querylens.auth.ownership import verify_query_run_ownership
from querylens.execution.cancellation import cancel_active_source_query, get_active_execution
from querylens.observability.logging import log_event
from querylens.persistence.repositories.query_runs import NONTERMINAL_STATES, TERMINAL_STATES, QueryRunRepository
from querylens.pipeline.orchestrator import cancel_active_task


def request_cancel(query_id: str, user_id: str) -> dict[str, Any]:
    """Idempotently cancel an active query run with source-level cleanup."""
    # 1. Authorize query ownership; returns 404 if inaccessible or foreign (Contract C02)
    verify_query_run_ownership(query_id, user_id)

    repo = QueryRunRepository()
    run = repo.get(query_id, user_id=user_id)

    # 2. Idempotent: If already in a terminal state, return current status
    if run["status"] in TERMINAL_STATES:
        return {"query_id": query_id, "status": run["status"]}

    # 3. Transition to 'cancelling' stage while cleanup executes
    repo.update_state(query_id, "cancelling")

    # 4. Cancel remote database statement if active
    handle = get_active_execution(query_id)
    if handle:
        cancel_active_source_query(handle)

    # 5. Cancel in-process asyncio task
    cancel_active_task(query_id)

    # 6. Mark terminal 'cancelled'
    repo.update_state(query_id, "cancelled", safe_message="Query was cancelled by user")
    log_event("query_cancelled", query_id=query_id, user_id=user_id)

    return {"query_id": query_id, "status": "cancelled"}
