"""Query history persistence repository with keyset pagination (Contracts C02, C09)."""

from __future__ import annotations

import base64
import datetime
from typing import Any
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import connections, query_runs
from querylens.jobs.results import get_result_cache


class HistoryRepository:
    """Owner-scoped query run history repository."""

    def __init__(self, conn: Connection | None = None) -> None:
        self._conn = conn

    def list_user_runs(
        self,
        user_id: str,
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """Fetch page of user query runs using stable created_at + id keyset pagination."""
        bounded_limit = max(1, min(limit, 100))

        stmt = (
            sa.select(*(query_runs.c[name] for name in (
                "id", "user_id", "connection_id", "question", "status", "state_version",
                "created_at", "updated_at", "max_rows", "origin", "parent_query_id",
                "source_query_id", "saved_question_id", "saved_question_version",
            )))
            .join(connections, connections.c.id == query_runs.c.connection_id)
            .where(query_runs.c.user_id == user_id, connections.c.user_id == user_id)
            .order_by(query_runs.c.created_at.desc(), query_runs.c.id.desc())
            .limit(bounded_limit + 1)
        )

        if cursor:
            try:
                raw = base64.b64decode(cursor).decode("utf-8")
                created_at_str, last_id = raw.split("|", 1)
                created_at = datetime.datetime.fromisoformat(created_at_str)
                stmt = stmt.where(
                    sa.or_(
                        query_runs.c.created_at < created_at,
                        sa.and_(
                            query_runs.c.created_at == created_at,
                            query_runs.c.id < last_id,
                        ),
                    )
                )
            except Exception:
                # Malformed cursor is ignored safely
                pass

        if self._conn:
            rows = self._conn.execute(stmt).fetchall()
        else:
            with get_db_connection() as c:
                rows = c.execute(stmt).fetchall()

        items = [dict(r._mapping) for r in rows]

        next_cursor: str | None = None
        if len(items) > bounded_limit:
            items = items[:bounded_limit]
            last = items[-1]
            dt_iso = last["created_at"].isoformat()
            cursor_payload = f"{dt_iso}|{last['id']}"
            next_cursor = base64.b64encode(cursor_payload.encode("utf-8")).decode("utf-8")

        return items, next_cursor

    def delete_run(self, query_id: str, user_id: str) -> bool:
        """Delete query run and cascade attempts/cache for authorized owner."""
        stmt = query_runs.delete().where(
            sa.and_(
                query_runs.c.id == query_id,
                query_runs.c.user_id == user_id,
            )
        )
        if self._conn:
            res = self._conn.execute(stmt)
        else:
            with get_db_connection() as c:
                res = c.execute(stmt)
        deleted = res.rowcount > 0
        if deleted:
            get_result_cache().evict(query_id)
        return deleted
