"""Read-only SQL execution without generation or repair."""

from __future__ import annotations

import uuid
from fastapi import HTTPException

from querylens.auth.ownership import verify_connection_ownership
from querylens.jobs.admission import JobReservation
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.pipeline.classifier import classify_pipeline_error
from querylens.pipeline.intent import build_run_context
from querylens.pipeline.lifecycle import RunServices, run_with_lifecycle
from querylens.schema.catalog import CatalogService
from querylens.semantics.versions import load_semantic_context
from querylens.sql.policy import validate_query_artifact
from querylens.utils.workers import run_db


def authorize_manual_source(source_query_id: str | None, user_id: str, connection_id: str) -> None:
    if source_query_id is None:
        return
    run = QueryRunRepository().get(source_query_id, user_id)
    if run["connection_id"] != connection_id or run["status"] != "completed":
        raise HTTPException(422, "Source must be a completed query on this connection")
    verify_connection_ownership(run["connection_id"], user_id)


async def run_manual_sql_pipeline(
    query_id: str,
    user_id: str,
    connection_id: str,
    sql: str,
    source_query_id: str | None = None,
    max_rows: int = 100,
    reservation: JobReservation | None = None,
) -> None:
    async def process(services: RunServices) -> None:
        repo = services.repo
        await run_db(verify_connection_ownership, connection_id, user_id)
        await run_db(authorize_manual_source, source_query_id, user_id, connection_id)
        await run_db(repo.update_state, query_id, "contextualizing")
        snapshot = await run_db(CatalogService().get_catalog, user_id, connection_id)
        semantics = await run_db(load_semantic_context, user_id, snapshot)
        attempt_id = str(uuid.uuid4())
        await run_db(
            repo.record_attempt,
            attempt_id=attempt_id,
            query_run_id=query_id,
            attempt_number=1,
            status="submitted",
            generated_sql=sql,
        )
        try:
            await run_db(repo.update_state, query_id, "validating")
            artifact = await run_db(validate_query_artifact, sql, connection_id, snapshot.engine, snapshot, max_rows)
            context = await run_db(
                build_run_context,
                artifact.template_sql,
                artifact.author_limit,
                "Edited SQL",
                "manual_sql",
                snapshot,
                semantics,
            )
            from querylens.pipeline.orchestrator import _semantic_warnings

            warnings = await run_db(_semantic_warnings, artifact.token, snapshot)
            await run_db(repo.update_state, query_id, "executing")
            result = await services.execute(artifact.token)
            published = await services.publish(artifact, result, context, [], warnings)
            await run_db(repo.finish_attempt, attempt_id, "completed" if published else "cancelled")
        except BaseException as exc:
            if not isinstance(exc, Exception):
                await run_db(repo.finish_attempt, attempt_id, "cancelled")
                raise
            error = classify_pipeline_error(exc, engine=snapshot.engine, snapshot=snapshot)
            await run_db(repo.finish_attempt, attempt_id, "failed", error.error_signature)
            # Manual SQL never repairs: validation errors are rejected directly.
            rejected = error.category in {"policy", "syntax", "unknown_identifier"}
            await run_db(
                repo.update_state,
                query_id,
                "rejected" if rejected else "failed",
                error_code=error.code,
                safe_message=error.safe_message,
            )

    await run_with_lifecycle(query_id, user_id, connection_id, reservation, process)
