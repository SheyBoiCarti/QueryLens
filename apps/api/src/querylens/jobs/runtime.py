"""Enforce process ownership for volatile jobs and results in production."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from querylens.persistence.session import get_engine


class RuntimeOwnership:
    """A dedicated PostgreSQL session owns this deployment until shutdown.

    A second worker/replica fails startup instead of splitting local result,
    cancellation and admission state. Keep this connection out of normal work.
    """

    def __init__(self) -> None:
        self.connection: Connection | None = None

    def acquire(self) -> None:
        connection = get_engine().connect()
        try:
            owned = connection.execute(sa.text("SELECT pg_try_advisory_lock(1873489271)")).scalar()
            connection.commit()
            if not owned:
                raise RuntimeError("QueryLens supports one API worker/replica per metadata database")
            self.connection = connection
        except BaseException:
            connection.close()
            raise

    def heartbeat(self) -> None:
        if self.connection is not None:
            # No reconnection: losing the owning session must stop this runtime.
            self.connection.execute(sa.text("SELECT 1"))
            self.connection.commit()

    def release(self) -> None:
        if self.connection is not None:
            try:
                self.connection.execute(sa.text("SELECT pg_advisory_unlock(1873489271)"))
                self.connection.commit()
            finally:
                self.connection.close()
                self.connection = None
