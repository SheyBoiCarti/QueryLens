"""Resource ownership enforcement and authorization checks (Contracts C02, C05)."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.api.errors import NotFoundError
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import connections, query_runs


def verify_connection_ownership(
    connection_id: str,
    user_id: str,
    conn: Connection | None = None,
) -> dict:
    """Verify user owns the connection. Returns connection dict or raises NotFoundError (404)."""
    stmt = sa.select(connections).where(
        connections.c.id == connection_id,
        connections.c.user_id == user_id,
    )
    if conn:
        row = conn.execute(stmt).fetchone()
    else:
        with get_db_connection() as c:
            row = c.execute(stmt).fetchone()

    if row is None:
        raise NotFoundError("Connection not found")
    return dict(row._mapping)


def verify_query_run_ownership(
    query_id: str,
    user_id: str,
    conn: Connection | None = None,
) -> dict:
    """Verify user owns the query run. Returns run dict or raises NotFoundError (404)."""
    stmt = sa.select(query_runs).where(
        query_runs.c.id == query_id,
        query_runs.c.user_id == user_id,
    )
    if conn:
        row = conn.execute(stmt).fetchone()
    else:
        with get_db_connection() as c:
            row = c.execute(stmt).fetchone()

    if row is None:
        raise NotFoundError("Query run not found")
    return dict(row._mapping)
