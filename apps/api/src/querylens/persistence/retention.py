"""Internal retention maintenance service (Contracts C04, C09)."""

from __future__ import annotations

import datetime
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import query_runs, sessions
from querylens.jobs.results import get_result_cache


def run_retention_cleanup(
    retention_days: int = 7,
    conn: Connection | None = None,
) -> dict[str, int]:
    """Remove expired sessions and query runs older than retention period."""
    now = datetime.datetime.now(datetime.timezone.utc)
    cutoff = now - datetime.timedelta(days=retention_days)

    def _execute(c: Connection) -> dict[str, int]:
        # 1. Clean expired / revoked sessions older than cutoff or expired
        sess_stmt = sessions.delete().where(
            sa.or_(
                sessions.c.expires_at < now,
                sa.and_(
                    sessions.c.revoked_at.isnot(None),
                    sessions.c.revoked_at < cutoff,
                ),
            )
        )
        sess_res = c.execute(sess_stmt)

        # Run-local context/definition snapshots are deleted with the run. Saved
        # definitions and their defaults remain independent. Lineage FKs SET NULL
        # while each surviving child retains its self-contained context.
        runs_stmt = query_runs.delete().where(query_runs.c.created_at < cutoff).returning(query_runs.c.id)
        deleted_ids = list(c.execute(runs_stmt).scalars())
        cache = get_result_cache()
        for query_id in deleted_ids:
            cache.evict(query_id)

        return {
            "deleted_sessions": sess_res.rowcount,
            "deleted_query_runs": len(deleted_ids),
        }

    if conn:
        return _execute(conn)
    else:
        with get_db_connection() as c:
            return _execute(c)
