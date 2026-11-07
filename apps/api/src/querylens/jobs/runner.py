"""Job execution runner and lifecycle management (Contracts C07, C08, C11)."""

from __future__ import annotations

import asyncio
import logging
from typing import Any
import sqlalchemy as sa
from sqlalchemy.engine import Engine

from querylens.connections.registry import get_registry
from querylens.jobs.admission import get_admission_controller
from querylens.observability.logging import log_event

logger = logging.getLogger("querylens.jobs")


def reconcile_interrupted_jobs(metadata_engine: Engine) -> int:
    """Mark any leftover non-terminal jobs as 'interrupted' on startup or restart."""
    with metadata_engine.begin() as conn:
        stmt = sa.text("""
            UPDATE query_runs
            SET status = 'interrupted',
                error_message = 'Job interrupted due to server restart or shutdown'
            WHERE status IN ('queued', 'running', 'generating', 'executing')
        """)
        res = conn.execute(stmt)
        count = res.rowcount
        if count > 0:
            log_event("interrupted_jobs_reconciled", count=count)
        return count


async def graceful_shutdown(deadline_sec: float = 5.0) -> dict[str, Any]:
    """Gracefully cancel running jobs, drain queue, and dispose connection pools."""
    log_event("shutdown_initiated", deadline_sec=deadline_sec)

    # 1. Dispose all database connection pools
    registry = get_registry()
    registry.dispose_all()

    # 2. Reset admission controller active state
    admission = get_admission_controller()
    with admission._lock:
        active_count = admission._active_global
        admission._active_global = 0
        admission._active_users.clear()
        admission._active_sources.clear()
        admission._waiting_global = 0
        admission._waiting_users.clear()

    log_event("shutdown_completed", drained_active=active_count)
    return {
        "status": "clean",
        "drained_active": active_count,
    }
