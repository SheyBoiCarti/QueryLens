"""Full query execution pipeline orchestrator with error classification and bounded repair (Contracts C05, C06, C07, C08, C09, C11)."""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Any

from querylens.auth.ownership import verify_connection_ownership
from querylens.config import get_settings
from querylens.execution.executor import SafeExecutor
from querylens.jobs.results import get_result_cache
from querylens.llm.fake import get_fake_llm_provider
from querylens.llm.live import get_live_llm_provider
from querylens.llm.protocol import GeneratedCandidate
from querylens.llm.provider import LLMProvider
from querylens.observability.logging import log_event
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.pipeline.classifier import classify_pipeline_error
from querylens.pipeline.context import build_schema_context
from querylens.pipeline.errors import ClassifiedError
from querylens.pipeline.loop_detection import LoopDetector
from querylens.pipeline.repair import RepairPolicy, RunAttemptBudget
from querylens.pipeline.repair_context import assemble_repair_context
from querylens.schema.catalog import CatalogService
from querylens.sql.policy import validate_and_bound_sql

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
    """Execute full natural-language query pipeline with bounded repair (Contract C08)."""
    repo = QueryRunRepository()
    catalog_service = CatalogService()
    if provider is not None:
        llm = provider
    else:
        settings = get_settings()
        if settings.environment != "test" and settings.llm_provider != "fake":
            llm = get_live_llm_provider(settings)
        else:
            llm = get_fake_llm_provider()
    cache = get_result_cache()

    budget = RunAttemptBudget(start_time=time.monotonic(), total_deadline_sec=30.0, cleanup_reserve_sec=5.0)
    loop_detector = LoopDetector()
    repair_policy = RepairPolicy()

    log_event("pipeline_start", run_id=query_id, status="queued")

    try:
        # 1. Stage: Contextualizing
        repo.update_state(query_id, "contextualizing")
        conn_dict = verify_connection_ownership(connection_id, user_id)
        snapshot = catalog_service.get_catalog(user_id, connection_id)
        schema_ctx = build_schema_context(snapshot)

        prior_sql: str | None = None
        last_error: ClassifiedError | None = None
        max_attempts = 3  # 1 initial generation + at most 2 repairs

        for attempt_number in range(1, max_attempts + 1):
            # Enforce budget before generation
            if budget.is_deadline_exceeded():
                repo.update_state(query_id, "failed", error_code="DEADLINE_EXCEEDED", safe_message="Query run deadline exceeded")
                log_event("pipeline_failed", run_id=query_id, error_code="DEADLINE_EXCEEDED")
                return

            if budget.is_tokens_exhausted():
                repo.update_state(query_id, "failed", error_code="TOKEN_BUDGET_EXCEEDED", safe_message="Token budget exceeded")
                log_event("pipeline_failed", run_id=query_id, error_code="TOKEN_BUDGET_EXCEEDED")
                return

            # Stage: Generating or Repairing
            current_stage = "generating" if attempt_number == 1 else "repairing"
            repo.update_state(query_id, current_stage)

            if attempt_number == 1:
                prompt_input = schema_ctx
            else:
                assert prior_sql is not None and last_error is not None
                repair_ctx = assemble_repair_context(
                    question=question,
                    dialect=conn_dict["engine"],
                    schema_context=schema_ctx,
                    prior_sql=prior_sql,
                    classified_error=last_error,
                    max_rows=max_rows,
                )
                prompt_input = repair_ctx.formatted_prompt

            gen_timeout = min(15.0, max(1.0, budget.time_remaining() - budget.cleanup_reserve_sec))
            try:
                candidate: GeneratedCandidate = await llm.generate(
                    question=question,
                    dialect=conn_dict["engine"],
                    schema_context=prompt_input,
                    timeout_sec=gen_timeout,
                )
            except Exception as e:
                classified_model_err = classify_pipeline_error(e, engine=conn_dict["engine"], snapshot=snapshot)
                repo.record_attempt(
                    attempt_id=str(uuid.uuid4()),
                    query_run_id=query_id,
                    attempt_number=attempt_number,
                    status="failed",
                    generated_sql=None,
                    error_signature=classified_model_err.error_signature,
                )
                repo.update_state(
                    query_id,
                    "failed",
                    error_code="MODEL_OUTPUT_INVALID",
                    safe_message=classified_model_err.safe_message,
                )
                return

            budget.add_tokens(candidate.usage.prompt_tokens + candidate.usage.completion_tokens)

            # Record durable attempt
            attempt_id = str(uuid.uuid4())
            repo.record_attempt(
                attempt_id=attempt_id,
                query_run_id=query_id,
                attempt_number=attempt_number,
                status="generated",
                generated_sql=candidate.sql,
                prompt_tokens=candidate.usage.prompt_tokens,
                completion_tokens=candidate.usage.completion_tokens,
                latency_ms=candidate.usage.latency_ms,
            )

            # Clarification check
            if candidate.requires_clarification:
                repo.update_state(
                    query_id,
                    "clarification_required",
                    clarification_question=candidate.clarification_question,
                )
                log_event("pipeline_clarification", run_id=query_id, status="clarification_required")
                return

            if not candidate.sql or not candidate.sql.strip():
                repo.update_state(
                    query_id,
                    "failed",
                    error_code="MODEL_OUTPUT_INVALID",
                    safe_message="Candidate contained no SQL query",
                )
                return

            prior_sql = candidate.sql

            # Loop detection on repeated query candidate
            if not loop_detector.check_candidate(candidate.sql):
                repo.update_state(
                    query_id,
                    "failed",
                    error_code="REPAIR_STALLED",
                    safe_message="Repair stalled on repeated query candidate",
                )
                log_event("pipeline_stalled", run_id=query_id, error_code="REPAIR_STALLED")
                return

            # Stage: Validating
            repo.update_state(query_id, "validating")
            try:
                validated_token = validate_and_bound_sql(
                    sql=candidate.sql,
                    connection_id=connection_id,
                    engine=conn_dict["engine"],
                    snapshot=snapshot,
                    max_rows=max_rows,
                )
            except Exception as e:
                classified = classify_pipeline_error(e, engine=conn_dict["engine"], snapshot=snapshot)
                last_error = classified

                if not classified.repairable:
                    target_status = "rejected" if classified.category == "policy" else "failed"
                    repo.update_state(
                        query_id,
                        target_status,
                        error_code=classified.code,
                        safe_message=classified.safe_message,
                    )
                    log_event("pipeline_error", run_id=query_id, status=target_status, error_code=classified.code)
                    return

                if not loop_detector.check_error_signature(classified.error_signature):
                    repo.update_state(
                        query_id,
                        "failed",
                        error_code="REPAIR_STALLED",
                        safe_message="Repair stalled on repeated error",
                    )
                    return

                decision = repair_policy.decide(classified, attempt_number, budget)
                if not decision.can_repair:
                    repo.update_state(
                        query_id,
                        "failed",
                        error_code=decision.reason or "MAX_ATTEMPTS_EXCEEDED",
                        safe_message=classified.safe_message,
                    )
                    return
                continue

            # Stage: Executing
            repo.update_state(query_id, "executing")
            try:
                exec_timeout = min(10.0, max(1.0, budget.time_remaining() - budget.cleanup_reserve_sec))
                result = SafeExecutor.execute(validated_token, timeout_sec=exec_timeout)
            except Exception as e:
                classified = classify_pipeline_error(e, engine=conn_dict["engine"], snapshot=snapshot)
                last_error = classified

                if not classified.repairable:
                    repo.update_state(
                        query_id,
                        "failed",
                        error_code=classified.code,
                        safe_message=classified.safe_message,
                    )
                    log_event("pipeline_error", run_id=query_id, status="failed", error_code=classified.code)
                    return

                if not loop_detector.check_error_signature(classified.error_signature):
                    repo.update_state(
                        query_id,
                        "failed",
                        error_code="REPAIR_STALLED",
                        safe_message="Repair stalled on repeated error",
                    )
                    return

                decision = repair_policy.decide(classified, attempt_number, budget)
                if not decision.can_repair:
                    repo.update_state(
                        query_id,
                        "failed",
                        error_code=decision.reason or "MAX_ATTEMPTS_EXCEEDED",
                        safe_message=classified.safe_message,
                    )
                    return
                continue

            # Execution succeeded
            cache.put(
                query_id=query_id,
                snapshot_hash=snapshot.snapshot_hash,
                columns=result.columns,
                rows=result.rows,
            )
            repo.update_state(query_id, "completed")
            log_event(
                "pipeline_completed",
                run_id=query_id,
                status="completed",
                row_count=result.row_count,
                duration_ms=result.execution_time_ms,
            )
            return

        # If loop finished without returning
        repo.update_state(
            query_id,
            "failed",
            error_code="MAX_ATTEMPTS_EXCEEDED",
            safe_message="Maximum repair attempts exceeded",
        )

    except asyncio.CancelledError:
        repo.update_state(query_id, "cancelled", safe_message="Query was cancelled by user")
        log_event("pipeline_cancelled", run_id=query_id, status="cancelled")
        raise

    except Exception as e:
        classified = classify_pipeline_error(e)
        repo.update_state(
            query_id,
            "failed",
            error_code=classified.code,
            safe_message=classified.safe_message,
        )
        log_event("pipeline_failed", run_id=query_id, status="failed", error_code=classified.code)

    finally:
        _active_tasks.pop(query_id, None)
