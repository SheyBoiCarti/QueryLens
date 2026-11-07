"""Active database source execution handle and cancellation coordinator (Contracts C03, C07, C08)."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any
import sqlalchemy as sa

from querylens.connections.registry import get_registry
from querylens.connections.service import ConnectionService
from querylens.observability.logging import log_event


@dataclass(frozen=True)
class ExecutionHandle:
    """Descriptor binding an active query run to its source backend PID."""

    query_id: str
    connection_id: str
    engine: str
    backend_pid: int
    lease_id: str


_registry_lock = threading.Lock()
_active_handles: dict[str, ExecutionHandle] = {}


def register_execution(handle: ExecutionHandle) -> None:
    """Register an in-flight source query execution handle."""
    with _registry_lock:
        _active_handles[handle.query_id] = handle


def unregister_execution(query_id: str) -> None:
    """Unregister an execution handle upon statement completion or release."""
    with _registry_lock:
        _active_handles.pop(query_id, None)


def get_active_execution(query_id: str) -> ExecutionHandle | None:
    """Retrieve active execution handle for a query run."""
    with _registry_lock:
        return _active_handles.get(query_id)


def cancel_active_source_query(handle: ExecutionHandle) -> bool:
    """Cancel active statement on the remote database using an isolated control connection (Contracts C03, C07)."""
    if not handle.backend_pid:
        return False

    try:
        from querylens.persistence.tables import connections
        from querylens.persistence.session import get_db_connection
        from querylens.connections.adapters import create_engine_with_pinning

        with get_db_connection() as c:
            row = c.execute(connections.select().where(connections.c.id == handle.connection_id)).fetchone()
            if not row:
                return False
            conn_dict = dict(row._mapping)

        registry = get_registry()
        engine_pool = registry.get_or_create(conn_dict)

        with engine_pool.connect() as conn:
            if handle.engine in ("postgresql", "postgres"):
                stmt = sa.text("SELECT pg_cancel_backend(:pid)")
                res = conn.execute(stmt, {"pid": handle.backend_pid}).scalar()
                log_event("source_cancel_sent", query_id=handle.query_id, engine="postgres", pid=handle.backend_pid, success=bool(res))
                return bool(res)
            elif handle.engine == "mysql":
                stmt = sa.text(f"KILL QUERY {int(handle.backend_pid)}")
                conn.execute(stmt)
                log_event("source_cancel_sent", query_id=handle.query_id, engine="mysql", pid=handle.backend_pid, success=True)
                return True
    except Exception as e:
        log_event("source_cancel_failed", query_id=handle.query_id, error=str(e))
        return False

    return False
