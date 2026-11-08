"""Shutdown and restart reconciliation for bounded in-process jobs."""

from __future__ import annotations

import asyncio
from typing import Any
from sqlalchemy.engine import Engine

from querylens.connections.registry import get_registry
from querylens.jobs.admission import get_admission_controller
from querylens.jobs.results import get_result_cache
from querylens.observability.logging import log_event
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.utils.workers import run_db


def reconcile_interrupted_jobs(metadata_engine: Engine) -> int:
    with metadata_engine.begin() as connection:
        return QueryRunRepository.mark_interrupted_runs(connection)


async def graceful_shutdown(deadline_sec: float = 5.0) -> dict[str, Any]:
    from querylens.pipeline.orchestrator import _active_tasks
    from querylens.execution.cancellation import signal_cancel

    get_admission_controller().stop()
    tasks = list(_active_tasks.items())
    for query_id, task in tasks:
        signal_cancel(query_id)
        task.cancel()
    pending: set[asyncio.Task[None]] = set()
    if tasks:
        _, pending = await asyncio.wait([task for _, task in tasks], timeout=deadline_sec)
    # Do not reset lease counters while DBAPI workers may still own sockets.
    await run_db(get_registry().dispose_all)
    get_result_cache().clear()
    log_event("shutdown_completed", cancelled=len(tasks), cleanup_pending=len(pending))
    return {"status": "pending" if pending else "clean", "drained_active": len(tasks) - len(pending)}
