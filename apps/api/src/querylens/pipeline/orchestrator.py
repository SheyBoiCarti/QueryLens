"""Bounded query orchestration with scoped policy, repair and source cancellation."""

from __future__ import annotations

import asyncio
import time
import uuid
from concurrent.futures import Future
from querylens.domain.query import QueryResult, ValidatedQuery
from querylens.domain.schema import CatalogSnapshot

from querylens.auth.ownership import verify_connection_ownership
from querylens.config import get_settings
from querylens.execution.cancellation import cancel_source, forget_execution, prepare_execution, terminate_source
from querylens.execution.executor import SafeExecutor
from querylens.jobs.admission import JobReservation, get_admission_controller
from querylens.jobs.results import get_result_cache
from querylens.llm.fake import get_fake_llm_provider
from querylens.llm.live import get_live_llm_provider
from querylens.llm.provider import LLMProvider
from querylens.observability.logging import log_event
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.pipeline.classifier import classify_pipeline_error
from querylens.pipeline.context import build_query_context, estimate_tokens
from querylens.semantics.versions import load_semantic_context
from querylens.pipeline.errors import ClassifiedError
from querylens.pipeline.loop_detection import LoopDetector
from querylens.pipeline.repair import RepairPolicy, RunAttemptBudget
from querylens.pipeline.repair_context import assemble_repair_context
from querylens.schema.catalog import CatalogService
from querylens.semantics.fanout import analyze_ast_semantics
from querylens.sql.parse import parse_query
from querylens.sql.policy import validate_and_bound_sql
from querylens.utils.workers import get_db_executor, run_db

_active_tasks: dict[str, asyncio.Task[None]] = {}


def register_active_task(query_id: str, task: asyncio.Task[None]) -> None:
    _active_tasks[query_id] = task


def cancel_active_task(query_id: str) -> bool:
    task = _active_tasks.get(query_id)
    if task and not task.done():
        task.cancel()
        return True
    return False


async def _execute_source(
    token: ValidatedQuery, query_id: str, timeout: float, reservation: JobReservation
) -> QueryResult:
    prepare_execution(query_id)
    work = get_db_executor().submit(SafeExecutor.execute, token, timeout_sec=timeout, query_id=query_id)
    reservation.work = work
    future = asyncio.wrap_future(work)
    try:
        return await asyncio.wait_for(asyncio.shield(future), timeout=timeout + get_settings().connect_timeout_sec)
    except (asyncio.CancelledError, TimeoutError):
        # Cancelling an asyncio waiter does not stop a DBAPI thread. Signal the
        # actual statement, and keep admission leased until the worker finishes.
        cleanup_deadline = time.monotonic() + get_settings().cleanup_timeout_sec
        try:
            await asyncio.wait_for(asyncio.to_thread(cancel_source, query_id), get_settings().cleanup_timeout_sec)
            remaining = cleanup_deadline - time.monotonic()
            if remaining > 0:
                await asyncio.wait_for(asyncio.shield(future), remaining)
        except (Exception, asyncio.CancelledError):
            # Graceful cancellation may fail if the server/network disappeared.
            # Wake the DBAPI worker by interrupting its existing source socket.
            if not work.done():
                terminate_source(query_id)  # Nonblocking shutdown of the existing socket; no queued worker needed.
            log_event("source_cleanup_pending", run_id=query_id)
        raise
    finally:

        def consume_result(completed: Future[QueryResult]) -> None:
            if not completed.cancelled():
                completed.exception()  # Retrieve failures after the request stopped waiting.
            forget_execution(query_id)

        work.add_done_callback(consume_result)
        if not future.done():
            future.add_done_callback(lambda completed: completed.exception() if not completed.cancelled() else None)


async def run_query_pipeline(
    query_id: str,
    user_id: str,
    connection_id: str,
    question: str,
    max_rows: int = 100,
    provider: LLMProvider | None = None,
    reservation: JobReservation | None = None,
) -> None:
    repo = QueryRunRepository()
    settings = get_settings()
    lease = reservation
    try:
        async with asyncio.timeout(settings.total_run_timeout_sec):
            lease = lease or get_admission_controller().reserve(user_id, connection_id)
            await lease.activate(settings.total_run_timeout_sec - settings.cleanup_timeout_sec)
            llm = provider or (
                get_live_llm_provider(settings)
                if settings.environment != "test" and settings.llm_provider != "fake"
                else get_fake_llm_provider()
            )
            await _process(repo, query_id, user_id, connection_id, question, max_rows, llm, lease)
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
        await run_db(repo.update_state, query_id, "failed", error_code=error.code, safe_message=error.safe_message)
        log_event("pipeline_failed", run_id=query_id, error_code=error.code)
    finally:
        if lease:
            lease.release()
            if lease.work is None or lease.work.done():
                forget_execution(query_id)
        _active_tasks.pop(query_id, None)


async def _process(
    repo: QueryRunRepository,
    query_id: str,
    user_id: str,
    connection_id: str,
    question: str,
    max_rows: int,
    llm: LLMProvider,
    lease: JobReservation,
) -> None:
    settings = get_settings()
    budget = RunAttemptBudget(
        total_deadline_sec=settings.total_run_timeout_sec,
        cleanup_reserve_sec=settings.cleanup_timeout_sec,
        max_cumulative_tokens=settings.max_cumulative_tokens,
        max_attempts=settings.max_repairs + 1,
    )
    detector = LoopDetector()
    repair = RepairPolicy()
    await run_db(repo.update_state, query_id, "contextualizing")
    connection = await run_db(verify_connection_ownership, connection_id, user_id)
    snapshot = await run_db(CatalogService().get_catalog, user_id, connection_id)
    semantic = await run_db(load_semantic_context, user_id, snapshot)
    context = await run_db(build_query_context, snapshot, question, settings.max_input_tokens, semantic)
    prior_sql: str | None = None
    last_error: ClassifiedError | None = None

    for number in range(1, budget.max_attempts + 1):
        if budget.is_deadline_exceeded():
            raise TimeoutError("Run deadline exhausted")
        if budget.is_tokens_exhausted():
            await run_db(
                repo.update_state,
                query_id,
                "failed",
                error_code="TOKEN_BUDGET_EXCEEDED",
                safe_message="Token budget exceeded",
            )
            return
        await run_db(repo.update_state, query_id, "generating" if number == 1 else "repairing")
        prompt = context
        if prior_sql and last_error:
            prompt = assemble_repair_context(
                question,
                connection["engine"],
                context,
                prior_sql,
                last_error,
                max_rows,
                max_tokens=max(1, settings.max_input_tokens - len(question.encode("utf-8")) - 2200),
            ).formatted_prompt
        generation_timeout = min(settings.generation_timeout_sec, budget.time_remaining() - budget.cleanup_reserve_sec)
        if generation_timeout <= 0:
            raise TimeoutError("Generation deadline exhausted")
        input_reservation = min(settings.max_input_tokens, estimate_tokens(prompt) + estimate_tokens(question) + 2200)
        if budget.cumulative_tokens + input_reservation + settings.max_output_tokens > settings.max_cumulative_tokens:
            await run_db(
                repo.update_state,
                query_id,
                "failed",
                error_code="TOKEN_BUDGET_EXCEEDED",
                safe_message="Insufficient token budget for another generation",
            )
            return
        attempt_id = str(uuid.uuid4())
        try:
            candidate = await asyncio.wait_for(
                llm.generate(
                    question=question,
                    dialect=connection["engine"],
                    schema_context=prompt,
                    timeout_sec=generation_timeout,
                ),
                generation_timeout,
            )
        except Exception as exc:
            error = classify_pipeline_error(exc)
            await run_db(
                repo.record_attempt,
                attempt_id=attempt_id,
                query_run_id=query_id,
                attempt_number=number,
                status="failed",
                error_signature=error.error_signature,
            )
            raise
        used_tokens = candidate.usage.prompt_tokens + candidate.usage.completion_tokens
        budget.add_tokens(used_tokens or input_reservation + settings.max_output_tokens)
        await run_db(
            repo.record_attempt,
            attempt_id=attempt_id,
            query_run_id=query_id,
            attempt_number=number,
            status="generated",
            generated_sql=candidate.sql,
            prompt_tokens=candidate.usage.prompt_tokens,
            completion_tokens=candidate.usage.completion_tokens,
            latency_ms=candidate.usage.latency_ms,
        )
        if candidate.requires_clarification:
            await run_db(
                repo.update_state,
                query_id,
                "clarification_required",
                clarification_question=candidate.clarification_question,
                assumptions=candidate.assumptions,
            )
            return
        if budget.cumulative_tokens > settings.max_cumulative_tokens:
            await run_db(
                repo.update_state,
                query_id,
                "failed",
                error_code="TOKEN_BUDGET_EXCEEDED",
                safe_message="Token budget exceeded",
            )
            return
        if not candidate.sql or not detector.check_candidate(candidate.sql):
            await run_db(
                repo.update_state,
                query_id,
                "failed",
                error_code="REPAIR_STALLED",
                safe_message="Repair repeated an earlier query",
            )
            return
        prior_sql = candidate.sql
        try:
            await run_db(repo.update_state, query_id, "validating")
            token = await run_db(
                validate_and_bound_sql, candidate.sql, connection_id, connection["engine"], snapshot, max_rows
            )
            warnings = await run_db(_semantic_warnings, token, snapshot)
            await run_db(repo.update_state, query_id, "executing")
            remaining = budget.time_remaining() - budget.cleanup_reserve_sec
            if remaining <= 0:
                raise TimeoutError("Execution deadline exhausted")
            result = await _execute_source(token, query_id, min(settings.statement_timeout_sec, remaining), lease)
        except Exception as exc:
            error = classify_pipeline_error(exc, engine=connection["engine"], snapshot=snapshot)
            await run_db(repo.finish_attempt, attempt_id, "failed", error.error_signature)
            last_error = error
            if not detector.check_error_signature(error.error_signature):
                await run_db(
                    repo.update_state,
                    query_id,
                    "failed",
                    error_code="REPAIR_STALLED",
                    safe_message="Repair repeated an earlier error",
                )
                return
            decision = repair.decide(error, number, budget)
            if decision.can_repair:
                continue
            await run_db(
                repo.update_state,
                query_id,
                "rejected" if error.category == "policy" else "failed",
                error_code=error.code if not error.repairable else decision.reason or error.code,
                safe_message=error.safe_message,
            )
            return
        # Refresh/revocation during generation or execution invalidates delivery too.
        latest = await run_db(CatalogService().get_catalog, user_id, connection_id)
        if latest.snapshot_hash != snapshot.snapshot_hash:
            raise PermissionError("Connection policy changed")
        get_result_cache().put(
            query_id, snapshot.snapshot_hash, result.columns, result.rows, connection_id=connection_id
        )
        await run_db(repo.finish_attempt, attempt_id, "completed")
        completed = await run_db(
            repo.update_state,
            query_id,
            "completed",
            canonical_sql=token.canonical_sql,
            assumptions=candidate.assumptions,
            warnings=warnings,
            truncated=result.truncated,
        )
        if not completed:
            get_result_cache().evict(query_id)
        log_event(
            "pipeline_completed", run_id=query_id, row_count=result.row_count, duration_ms=result.execution_time_ms
        )
        return


def _semantic_warnings(token: ValidatedQuery, snapshot: CatalogSnapshot) -> list[str]:
    return [
        warning.message for warning in analyze_ast_semantics(parse_query(token.canonical_sql, token.engine), snapshot)
    ]
