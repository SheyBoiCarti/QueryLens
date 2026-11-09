"""Maintain a single persistent owner for the shared workspace."""

import sqlalchemy as sa

from querylens.auth.dependencies import DEFAULT_DEV_USER
from querylens.persistence.session import get_db_connection
from querylens.persistence.tables import users, connections, query_runs, saved_questions


def initialize_workspace() -> None:
    """Preserve resources from earlier user accounts in the shared workspace."""
    workspace_id = DEFAULT_DEV_USER["user_id"]
    with get_db_connection() as conn:
        if not conn.execute(sa.select(users.c.id).where(users.c.id == workspace_id)).scalar():
            conn.execute(users.insert().values(
                id=workspace_id, email=DEFAULT_DEV_USER["email"],
                password_hash="disabled", role="admin",
            ))
        for table in (connections, query_runs, saved_questions):
            conn.execute(table.update().where(table.c.user_id != workspace_id).values(user_id=workspace_id))
