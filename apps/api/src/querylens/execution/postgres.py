"""PostgreSQL restricted execution engine (Contracts C03, C06, C07)."""

from __future__ import annotations

import time
import uuid
from querylens.config import get_settings
from querylens.execution.cancellation import (
    ExecutionHandle,
    register_execution,
    unregister_execution,
    check_cancelled,
    shutdown_source_socket,
)
from sqlalchemy.engine import Engine

from querylens.domain.query import QueryResult, ValidatedQuery
from querylens.execution.bounds import bounded_source_sql, fetch_bounded_rows, metadata_probe_sql


def execute_postgres_restricted(
    engine: Engine,
    query: ValidatedQuery,
    timeout_sec: float = 10.0,
    query_id: str | None = None,
) -> QueryResult:
    """Execute ValidatedQuery on PostgreSQL inside restricted read-only transaction."""
    start_time = time.time()

    # Raw connection from engine pool
    with engine.raw_connection() as raw_conn:
        # psycopg connection
        conn = raw_conn.driver_connection
        if conn is None:
            raise ConnectionError("Source pool returned a closed connection")
        check_cancelled(query_id)
        try:
            if query_id:
                register_execution(
                    ExecutionHandle(
                        query_id,
                        query.connection_id,
                        query.engine,
                        conn.info.backend_pid,
                        str(uuid.uuid4()),
                        lambda: conn.cancel_safe(timeout=get_settings().cleanup_timeout_sec),
                        lambda: shutdown_source_socket(conn, query.engine),
                    )
                )
            with conn.cursor() as cur:
                # Enforce Contract C07 parameters before query
                cur.execute("SET TRANSACTION READ ONLY;")
                cur.execute("SET LOCAL timezone = 'UTC';")
                cur.execute("SET LOCAL search_path = pg_catalog;")
                cur.execute(f"SET LOCAL statement_timeout = '{int(timeout_sec * 1000)}ms';")
                cur.execute(f"SET LOCAL lock_timeout = '{max(1, int(get_settings().lock_timeout_sec * 1000))}ms';")

                # Probe only metadata; no source values are transferred here.
                cur.execute(metadata_probe_sql(query.canonical_sql, query.engine))
                col_desc = list(cur.description or [])
            stream = conn.cursor(name=f"querylens_{uuid.uuid4().hex}")
            try:
                check_cancelled(query_id)
                stream.execute(bounded_source_sql(query.canonical_sql, len(col_desc), query.engine))
                columns, rows, truncated = fetch_bounded_rows(stream, col_desc, query.max_rows)
            except BaseException:
                # Avoid draining an oversized unbuffered result on cursor close.
                raw_conn.invalidate()
                raise
            finally:
                if raw_conn.is_valid:
                    stream.close()

        finally:
            try:
                if raw_conn.is_valid:
                    try:
                        conn.rollback()
                    except Exception:
                        raw_conn.invalidate()
                        raise
            finally:
                # Retain the cancellation handle through rollback/reset too.
                if query_id:
                    unregister_execution(query_id)

    elapsed_ms = int((time.time() - start_time) * 1000)

    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        execution_time_ms=elapsed_ms,
    )
