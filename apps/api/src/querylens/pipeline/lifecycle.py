"""Admission, deadlines, cancellation, and atomic publication shared by every origin."""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastapi import HTTPException

from querylens.config import get_settings
from querylens.domain.analytics import RunContext
from querylens.domain.query import QueryResult, ValidatedArtifact, ValidatedQuery
from querylens.execution.cancellation import forget_execution
from querylens.execution.executor import ExecutionSecurityError
from querylens.jobs.admission import JobReservation, get_admission_controller
from querylens.jobs.results import get_result_cache
from querylens.observability.logging import log_event
from querylens.persistence.repositories.query_runs import QueryRunRepository, TERMINAL_STATES
from querylens.persistence.session import get_db_connection
from querylens.pipeline.classifier import classify_pipeline_error
from querylens.schema.snapshots import get_latest_snapshot
from querylens.semantics.versions import lock_semantic_connection
from querylens.utils.workers import run_db


@dataclass
class RunServices:
    query_id: str
    user_id: str
    connection_id: str
    reservation: JobReservation
    deadline: float
    repo: QueryRunRepository

    async def execute(self, token: ValidatedQuery) -> QueryResult:
        # Keep the established execution hook compatible with cancellation tests
        # and the original bounded DBAPI thread cleanup implementation.
        from querylens.pipeline import orchestrator

        settings = get_settings()
        remaining = self.deadline - time.monotonic() - settings.cleanup_timeout_sec
        if remaining <= 0:
            raise TimeoutError("Execution deadline exhausted")
        if token.max_rows > settings.max_max_rows or len(token.canonical_sql.encode("utf-8")) > settings.max_sql_bytes:
            raise ExecutionSecurityError("Configured execution budget changed")
        run = await run_db(self.repo.get, self.query_id, self.user_id)
        if run["status"] in TERMINAL_STATES:
            raise asyncio.CancelledError()
        return await orchestrator._execute_source(
            token, self.query_id, min(settings.statement_timeout_sec, remaining), self.reservation
        )

    async def publish(
        self,
        artifact: ValidatedArtifact,
        result: QueryResult,
        context: RunContext,
        assumptions: list[str],
        warnings: list[str],
    ) -> bool:
        return await run_db(self._publish, artifact, result, context, assumptions, warnings)

    def _publish(self, artifact, result, context, assumptions, warnings) -> bool:
        cache = get_result_cache()
        try:
            with get_db_connection() as conn:
                snapshot = get_latest_snapshot(self.connection_id, conn)
                if snapshot is None or snapshot.snapshot_hash != context.snapshot_hash:
                    raise ExecutionSecurityError("Physical catalog changed")
                try:
                    connection = lock_semantic_connection(conn, self.user_id, snapshot, read=True)
                except HTTPException as exc:
                    raise ExecutionSecurityError("Connection policy changed") from exc
                if (
                    connection["policy_version"] != context.policy_version
                    or connection["semantic_version"] != context.semantic_version
                ):
                    raise ExecutionSecurityError("Connection policy or semantics changed")
                cache.put(
                    self.query_id, context.snapshot_hash, result.columns, result.rows, connection_id=self.connection_id
                )
                completed = QueryRunRepository(conn).complete(
                    self.query_id, context, artifact.token.canonical_sql, assumptions, warnings, result.truncated
                )
            if not completed:
                cache.evict(self.query_id)
            else:
                log_event(
                    "pipeline_completed",
                    run_id=self.query_id,
                    row_count=result.row_count,
                    duration_ms=result.execution_time_ms,
                )
            return completed
        except BaseException:
            cache.evict(self.query_id)
            raise


async def run_with_lifecycle(
    query_id: str,
    user_id: str,
    connection_id: str,
    reservation: JobReservation | None,
    process: Callable[[RunServices], Awaitable[None]],
) -> None:
    repo = QueryRunRepository()
    settings = get_settings()
    lease = reservation
    started = time.monotonic()
    try:
        async with asyncio.timeout(settings.total_run_timeout_sec):
            lease = lease or get_admission_controller().reserve(user_id, connection_id)
            await lease.activate(settings.total_run_timeout_sec - settings.cleanup_timeout_sec)
            run = await run_db(repo.get, query_id, user_id)
            if run["status"] in TERMINAL_STATES:
                return
            await process(
                RunServices(query_id, user_id, connection_id, lease, started + settings.total_run_timeout_sec, repo)
            )
    except asyncio.CancelledError:
        await run_db(repo.update_state, query_id, "cancelled", safe_message="Query was cancelled")
        log_event("pipeline_cancelled", run_id=query_id)
        raise
    except TimeoutError:
        await run_db(
            repo.update_state,
            query_id,
            "failed",
            error_code="DEADLINE_EXCEEDED",
            safe_message="Query run deadline exceeded",
        )
    except Exception as exc:
        error = classify_pipeline_error(exc)
        await run_db(
            repo.update_state,
            query_id,
            "rejected" if error.category == "policy" else "failed",
            error_code=error.code,
            safe_message=error.safe_message,
        )
        log_event("pipeline_failed", run_id=query_id, error_code=error.code)
    finally:
        if lease:
            lease.release()
            if lease.work is None or lease.work.done():
                forget_execution(query_id)
        from querylens.pipeline.orchestrator import _active_tasks

        _active_tasks.pop(query_id, None)
