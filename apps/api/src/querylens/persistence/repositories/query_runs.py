"""Query runs and attempts metadata repository (Contracts C02, C08)."""

from __future__ import annotations

import datetime
from typing import Any
import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.api.errors import NotFoundError
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import query_attempts, query_runs

TERMINAL_STATES = {
    "completed",
    "failed",
    "rejected",
    "clarification_required",
    "cancelled",
    "interrupted",
}

NONTERMINAL_STATES = {
    "queued",
    "contextualizing",
    "generating",
    "validating",
    "executing",
    "repairing",
    "cancelling",
}


class QueryRunRepository:
    """Manages persistence and state transitions for query runs and attempts."""

    def __init__(self, conn: Connection | None = None) -> None:
        self._conn = conn

    def create(
        self,
        query_id: str,
        user_id: str,
        connection_id: str,
        question: str,
        max_rows: int = 100,
    ) -> dict[str, Any]:
        """Create initial queued query run record."""
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = query_runs.insert().values(
            id=query_id,
            user_id=user_id,
            connection_id=connection_id,
            status="queued",
            state_version=1,
            question=question,
            max_rows=max_rows,
            created_at=now,
            updated_at=now,
        )
        if self._conn:
            self._conn.execute(stmt)
        else:
            with get_db_connection() as c:
                c.execute(stmt)

        return {
            "query_id": query_id,
            "user_id": user_id,
            "connection_id": connection_id,
            "status": "queued",
            "state_version": 1,
            "question": question,
            "max_rows": max_rows,
            "created_at": now,
            "updated_at": now,
        }

    def get(self, query_id: str, user_id: str | None = None) -> dict[str, Any]:
        """Fetch query run, checking user ownership if provided (Contract C02)."""
        conditions = [query_runs.c.id == query_id]
        if user_id is not None:
            conditions.append(query_runs.c.user_id == user_id)

        stmt = sa.select(query_runs).where(*conditions)
        if self._conn:
            row = self._conn.execute(stmt).fetchone()
        else:
            with get_db_connection() as c:
                row = c.execute(stmt).fetchone()

        if row is None:
            raise NotFoundError("Query run not found")
        return dict(row._mapping)

    def update_state(
        self,
        query_id: str,
        new_status: str,
        error_code: str | None = None,
        safe_message: str | None = None,
        clarification_question: str | None = None,
    ) -> bool:
        """Atomic state transition with terminal guard (Contract C08)."""
        now = datetime.datetime.now(datetime.timezone.utc)

        def _execute(conn: Connection) -> bool:
            # Check current status
            curr = conn.execute(
                sa.select(query_runs.c.status, query_runs.c.state_version)
                .where(query_runs.c.id == query_id)
            ).fetchone()
            if not curr:
                return False

            curr_status, curr_ver = curr[0], curr[1]
            # Terminal states cannot be overwritten by later events (Contract C08)
            if curr_status in TERMINAL_STATES:
                return False

            updates: dict[str, Any] = {
                "status": new_status,
                "state_version": curr_ver + 1,
                "updated_at": now,
            }
            if error_code is not None:
                updates["error_code"] = error_code
            if safe_message is not None:
                updates["safe_message"] = safe_message
            if clarification_question is not None:
                updates["clarification_question"] = clarification_question

            res = conn.execute(
                query_runs.update()
                .where(
                    query_runs.c.id == query_id,
                    query_runs.c.status.notin_(TERMINAL_STATES),
                )
                .values(**updates)
            )
            return res.rowcount > 0

        if self._conn:
            return _execute(self._conn)
        else:
            with get_db_connection() as c:
                return _execute(c)

    def record_attempt(
        self,
        attempt_id: str,
        query_run_id: str,
        attempt_number: int,
        status: str,
        generated_sql: str | None = None,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        latency_ms: int = 0,
        error_signature: str | None = None,
    ) -> None:
        """Record durable attempt diagnostics."""
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = query_attempts.insert().values(
            id=attempt_id,
            query_run_id=query_run_id,
            attempt_number=attempt_number,
            generated_sql=generated_sql,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            latency_ms=latency_ms,
            error_signature=error_signature,
            created_at=now,
        )
        if self._conn:
            self._conn.execute(stmt)
        else:
            with get_db_connection() as c:
                c.execute(stmt)

    def get_attempts(self, query_run_id: str) -> list[dict[str, Any]]:
        """Get all attempts for query in ordinal order."""
        stmt = (
            sa.select(query_attempts)
            .where(query_attempts.c.query_run_id == query_run_id)
            .order_by(query_attempts.c.attempt_number.asc())
        )
        if self._conn:
            rows = self._conn.execute(stmt).fetchall()
        else:
            with get_db_connection() as c:
                rows = c.execute(stmt).fetchall()
        return [dict(r._mapping) for r in rows]

    @staticmethod
    def mark_interrupted_runs(conn: Connection | None = None) -> int:
        """Mark all prior nonterminal runs interrupted on API process restart (Contract C08)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = (
            query_runs.update()
            .where(query_runs.c.status.in_(NONTERMINAL_STATES))
            .values(
                status="interrupted",
                error_code="PROCESS_INTERRUPTED",
                safe_message="Server process restarted while query was in flight",
                updated_at=now,
            )
        )
        if conn:
            res = conn.execute(stmt)
        else:
            with get_db_connection() as c:
                res = c.execute(stmt)
        return res.rowcount
