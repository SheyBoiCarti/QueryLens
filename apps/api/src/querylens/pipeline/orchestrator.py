"""Full query execution pipeline orchestrator (Contracts C05, C06, C07, C08, C09)."""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

from querylens.auth.ownership import verify_connection_ownership
from querylens.execution.executor import SafeExecutor
from querylens.jobs.results import get_result_cache
from querylens.llm.fake import get_fake_llm_provider
from querylens.llm.protocol import GeneratedCandidate
from querylens.llm.provider import LLMProvider
from querylens.observability.logging import log_event
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.pipeline.context import build_schema_context
from querylens.schema.catalog import CatalogService
from querylens.sql.policy import SQLPolicyViolationError, validate_and_bound_sql

# Active in-flight query task handles: query_id -> asyncio.Task
_active_tasks: dict[str, asyncio.Task] = {}


def register_active_task(query_id: str, task: asyncio.Task) -> None:
    _active_tasks[query_id] = task


def cancel_active_task(query_id: str) -> bool:
    task = _active_tasks.pop(query_id, None)
    if task and not task.done():
        task.cancel()
        return True
    return False


async def run_query_pipeline(
    query_id: str,
    user_id: str,
    connection_id: str,
    question: str,
    max_rows: int = 100,
    provider: LLMProvider | None = None,
) -> None:
    """Execute full natural-language query vertical slice."""
    repo = QueryRunRepository()
    catalog_service = CatalogService()
    llm = provider or get_fake_llm_provider()
    cache = get_result_cache()

    log_event("pipeline_start", run_id=query_id, status="queued")

    try:
        # 1. Stage: Contextualizing
        repo.update_state(query_id, "contextualizing")
        conn_dict = verify_connection_ownership(connection_id, user_id)
        snapshot = catalog_service.get_catalog(user_id, connection_id)
        schema_ctx = build_schema_context(snapshot)

        # 2. Stage: Generating
        repo.update_state(query_id, "generating")
        candidate: GeneratedCandidate = await llm.generate(
            question=question,
            dialect=conn_dict["engine"],
            schema_context=schema_ctx,
            timeout_sec=15.0,
        )

        attempt_id = str(uuid.uuid4())
        repo.record_attempt(
            attempt_id=attempt_id,
            query_run_id=query_id,
            attempt_number=1,
            status="generated",
            generated_sql=candidate.sql,
            prompt_tokens=candidate.usage.prompt_tokens,
            completion_tokens=candidate.usage.completion_tokens,
            latency_ms=candidate.usage.latency_ms,
        )

        # 3. Clarification check (Contract C08: no SQL validation or execution)
        if candidate.requires_clarification:
            repo.update_state(
                query_id,
                "clarification_required",
                clarification_question=candidate.clarification_question,
            )
            log_event("pipeline_clarification", run_id=query_id, status="clarification_required")
            return

        # 4. Stage: Validating
        repo.update_state(query_id, "validating")
        assert candidate.sql is not None
        validated_token = validate_and_bound_sql(
            sql=candidate.sql,
            connection_id=connection_id,
            engine=conn_dict["engine"],
            snapshot=snapshot,
            max_rows=max_rows,
        )

        # 5. Stage: Executing
        repo.update_state(query_id, "executing")
        result = SafeExecutor.execute(validated_token, timeout_sec=10.0)

        # 6. Cache rows in volatile memory
        cache.put(
            query_id=query_id,
            snapshot_hash=snapshot.snapshot_hash,
            columns=result.columns,
            rows=result.rows,
        )

        # 7. Terminal Stage: Completed
        repo.update_state(query_id, "completed")
        log_event(
            "pipeline_completed",
            run_id=query_id,
            status="completed",
            row_count=result.row_count,
            duration_ms=result.execution_time_ms,
        )

    except asyncio.CancelledError:
        repo.update_state(query_id, "cancelled", safe_message="Query was cancelled by user")
        log_event("pipeline_cancelled", run_id=query_id, status="cancelled")
        raise

    except SQLPolicyViolationError as pe:
        repo.update_state(query_id, "rejected", error_code="POLICY_VIOLATION", safe_message=str(pe))
        log_event("pipeline_rejected", run_id=query_id, status="rejected", error_code="POLICY_VIOLATION")

    except Exception as e:
        repo.update_state(
            query_id,
            "failed",
            error_code="PIPELINE_ERROR",
            safe_message="Failed to process query",
        )
        log_event("pipeline_failed", run_id=query_id, status="failed", error_code="PIPELINE_ERROR")

    finally:
        _active_tasks.pop(query_id, None)
