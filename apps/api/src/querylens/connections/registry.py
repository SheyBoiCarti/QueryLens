"""Connection pool registry and lifecycle manager (Contracts C03, C07)."""

from __future__ import annotations

import time
import hashlib
import threading
from typing import NamedTuple
from sqlalchemy.engine import Engine

from querylens.connections.adapters import create_engine_pool


class PoolEntry(NamedTuple):
    engine: Engine
    last_used: float
    signature: str


class ConnectionRegistry:
    """Bounded connection pool registry with LRU eviction and disposal (Contract C07)."""

    def __init__(self, max_idle_pools: int = 8) -> None:
        self._lock = threading.RLock()
        self._max_idle_pools = max_idle_pools
        self._pools: dict[str, PoolEntry] = {}

    def get_or_create(
        self,
        connection_id: str,
        engine_name: str,
        host: str,
        port: int,
        database: str,
        username: str,
        password: str,
        tls_enabled: bool = True,
        ca_cert: str | None = None,
    ) -> Engine:
        """Get existing pool or create new bounded engine pool."""
        with self._lock:
            signature = hashlib.sha256(
                repr((engine_name, host, port, database, username, password, tls_enabled, ca_cert)).encode()
            ).hexdigest()
            now = time.time()
            if connection_id in self._pools and self._pools[connection_id].signature != signature:
                self.dispose(connection_id)
            if connection_id in self._pools:
                entry = self._pools[connection_id]
                self._pools[connection_id] = PoolEntry(engine=entry.engine, last_used=now, signature=signature)
                return entry.engine

            # Enforce max idle pools: evict oldest if at capacity
            if len(self._pools) >= self._max_idle_pools:
                oldest_id = min(self._pools.keys(), key=lambda k: self._pools[k].last_used)
                self.dispose(oldest_id)

            engine = create_engine_pool(
                engine_name=engine_name,
                host=host,
                port=port,
                database=database,
                username=username,
                password=password,
                tls_enabled=tls_enabled,
                ca_cert=ca_cert,
            )
            self._pools[connection_id] = PoolEntry(engine=engine, last_used=now, signature=signature)
            return engine

    def dispose(self, connection_id: str) -> None:
        """Dispose and remove engine pool."""
        with self._lock:
            entry = self._pools.pop(connection_id, None)
            if entry is not None:
                entry.engine.dispose()

    def dispose_all(self) -> None:
        """Dispose all connection pools."""
        with self._lock:
            for entry in self._pools.values():
                entry.engine.dispose()
            self._pools.clear()


_registry: ConnectionRegistry | None = None


def get_registry() -> ConnectionRegistry:
    """Get singleton ConnectionRegistry."""
    global _registry
    if _registry is None:
        _registry = ConnectionRegistry()
    return _registry
