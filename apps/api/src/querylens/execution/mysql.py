"""MySQL restricted execution engine (Contracts C03, C06, C07)."""

from __future__ import annotations

import time
from typing import Any
from sqlalchemy.engine import Engine

from querylens.domain.query import QueryResult, ValidatedQuery
from querylens.execution.serializer import serialize_result_set


def execute_mysql_restricted(
    engine: Engine,
    query: ValidatedQuery,
    timeout_sec: float = 10.0,
) -> QueryResult:
    """Execute ValidatedQuery on MySQL inside restricted read-only transaction."""
    start_time = time.time()

    with engine.raw_connection() as raw_conn:
        conn = raw_conn.connection if hasattr(raw_conn, "connection") else raw_conn
        with conn.cursor() as cur:
            # Enforce Contract C07 parameters before query
            cur.execute("SET time_zone = '+00:00';")
            cur.execute("SET sql_mode = 'STRICT_TRANS_TABLES,NO_ENGINE_SUBSTITUTION';")
            cur.execute("START TRANSACTION READ ONLY;")
            timeout_ms = int(timeout_sec * 1000)
            cur.execute(f"SET SESSION max_execution_time = {timeout_ms};")

            # Execute canonical bounded SQL
            cur.execute(query.canonical_sql)

            # Fetch at most max_rows + 1 (sentinel row for truncation)
            fetch_limit = query.max_rows + 1
            raw_rows = cur.fetchmany(fetch_limit)
            col_desc = cur.description or []

        conn.rollback()

    elapsed_ms = int((time.time() - start_time) * 1000)

    columns, rows, truncated = serialize_result_set(
        columns_desc=col_desc,
        raw_rows=raw_rows,
        max_rows=query.max_rows,
    )

    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        truncated=truncated,
        execution_time_ms=elapsed_ms,
    )
