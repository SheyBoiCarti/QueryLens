"""Thread-safe, volatile TTL result cache; never persist source rows."""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from typing import Any

RESULT_CACHE_TTL_SEC = 300
RESULT_CACHE_MAX_BYTES = 33554432


@dataclass(frozen=True)
class CacheEntry:
    connection_id: str
    snapshot_hash: str
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    approx_bytes: int
    expires_at: float


class ResultCache:
    def __init__(self, max_bytes: int = RESULT_CACHE_MAX_BYTES, ttl_sec: int = RESULT_CACHE_TTL_SEC) -> None:
        self._max_bytes = max_bytes
        self._ttl_sec = ttl_sec
        self._cache: dict[str, CacheEntry] = {}
        self._total_bytes = 0
        self._lock = threading.RLock()

    def _evict(self, query_id: str) -> None:
        entry = self._cache.pop(query_id, None)
        if entry:
            self._total_bytes -= entry.approx_bytes

    def _purge_expired(self, now: float) -> None:
        for key in [key for key, entry in self._cache.items() if entry.expires_at <= now]:
            self._evict(key)

    def put(
        self,
        query_id: str,
        snapshot_hash: str,
        columns: list[dict[str, str]],
        rows: list[dict[str, Any]],
        connection_id: str = "",
    ) -> None:
        size = len(json.dumps([columns, rows], ensure_ascii=False).encode("utf-8")) + 1024
        with self._lock:
            self._purge_expired(time.monotonic())
            self._evict(query_id)
            if size > self._max_bytes:
                return
            while self._cache and self._total_bytes + size > self._max_bytes:
                self._evict(min(self._cache, key=lambda key: self._cache[key].expires_at))
            self._cache[query_id] = CacheEntry(
                connection_id, snapshot_hash, columns, rows, size, time.monotonic() + self._ttl_sec
            )
            self._total_bytes += size

    def get(
        self, query_id: str, snapshot_hash: str | None = None
    ) -> tuple[list[dict[str, str]], list[dict[str, Any]]] | None:
        with self._lock:
            self._purge_expired(time.monotonic())
            entry = self._cache.get(query_id)
            if entry is None:
                return None
            if snapshot_hash is not None and entry.snapshot_hash != snapshot_hash:
                self._evict(query_id)
                return None
            return entry.columns, entry.rows

    def evict(self, query_id: str) -> None:
        with self._lock:
            self._evict(query_id)

    def evict_connection(self, connection_id: str) -> None:
        with self._lock:
            for key in [key for key, entry in self._cache.items() if entry.connection_id == connection_id]:
                self._evict(key)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()
            self._total_bytes = 0


_global_result_cache: ResultCache | None = None


def get_result_cache() -> ResultCache:
    global _global_result_cache
    if _global_result_cache is None:
        from querylens.config import get_settings

        settings = get_settings()
        _global_result_cache = ResultCache(settings.result_cache_bytes, settings.result_cache_ttl_sec)
    return _global_result_cache
