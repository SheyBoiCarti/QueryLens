"""Repository for owner-scoped saved question persistence (Contract C09)."""

from __future__ import annotations

import datetime as dt
from typing import Any
import sqlalchemy as sa

from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import saved_questions


class SavedQuestionRepository:
    """Manages saved questions with owner isolation and optimistic revision control."""

    def create(self, record: dict[str, Any]) -> dict[str, Any]:
        with get_db_connection() as conn:
            stmt = saved_questions.insert().values(**record)
            conn.execute(stmt)
            item = self.get_with_conn(record["id"], record["user_id"], conn)
            assert item is not None
            return item

    def get(self, id: str, user_id: str) -> dict[str, Any] | None:
        with get_db_connection() as conn:
            return self.get_with_conn(id, user_id, conn)

    def get_with_conn(self, id: str, user_id: str, conn: sa.Connection) -> dict[str, Any] | None:
        stmt = sa.select(saved_questions).where(
            saved_questions.c.id == id,
            saved_questions.c.user_id == user_id,
        )
        row = conn.execute(stmt).fetchone()
        if row is None:
            return None
        return dict(row._mapping)

    def list_for_connection(
        self,
        connection_id: str,
        user_id: str,
        search: str | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> tuple[list[dict[str, Any]], str | None]:
        with get_db_connection() as conn:
            stmt = sa.select(saved_questions).where(
                saved_questions.c.connection_id == connection_id,
                saved_questions.c.user_id == user_id,
            )
            if search and search.strip():
                escaped = search.strip().replace("%", "\\%").replace("_", "\\_")
                stmt = stmt.where(saved_questions.c.title.ilike(f"%{escaped}%"))

            stmt = stmt.order_by(saved_questions.c.created_at.desc(), saved_questions.c.id.desc())

            if cursor:
                parts = cursor.split("_", 1)
                if len(parts) == 2:
                    try:
                        c_time = dt.datetime.fromisoformat(parts[0])
                        c_id = parts[1]
                        stmt = stmt.where(
                            sa.or_(
                                saved_questions.c.created_at < c_time,
                                sa.and_(
                                    saved_questions.c.created_at == c_time,
                                    saved_questions.c.id < c_id,
                                ),
                            )
                        )
                    except ValueError:
                        pass

            bounded_limit = max(1, min(limit, 100))
            rows = conn.execute(stmt.limit(bounded_limit + 1)).fetchall()
            items = [dict(r._mapping) for r in rows[:bounded_limit]]
            next_cursor = None
            if len(rows) > bounded_limit:
                last_item = items[-1]
                t_val = last_item["created_at"]
                t_str = t_val.isoformat() if hasattr(t_val, "isoformat") else str(t_val)
                next_cursor = f"{t_str}_{last_item['id']}"
            return items, next_cursor

    def update(
        self,
        id: str,
        user_id: str,
        expected_revision: int,
        changes: dict[str, Any],
    ) -> dict[str, Any] | None:
        with get_db_connection() as conn:
            stmt = (
                saved_questions.update()
                .where(
                    saved_questions.c.id == id,
                    saved_questions.c.user_id == user_id,
                    saved_questions.c.revision == expected_revision,
                )
                .values(
                    **changes,
                    revision=expected_revision + 1,
                    updated_at=dt.datetime.now(dt.timezone.utc),
                )
            )
            res = conn.execute(stmt)
            if res.rowcount == 0:
                return None
            return self.get_with_conn(id, user_id, conn)

    def delete(self, id: str, user_id: str) -> bool:
        with get_db_connection() as conn:
            stmt = saved_questions.delete().where(
                saved_questions.c.id == id,
                saved_questions.c.user_id == user_id,
            )
            res = conn.execute(stmt)
            return res.rowcount > 0
