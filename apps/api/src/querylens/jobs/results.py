"""Volatile in-memory TTL result cache (Contracts C07, C09)."""

from __future__ import annotations

import time
from typing import Any, NamedTuple

RESULT_CACHE_TTL_SEC = 300
RESULT_CACHE_MAX_BYTES = 33554432  # 32 MiB


class CacheEntry(NamedTuple):
    query_id: str
    snapshot_hash: str
    columns: list[dict[str, str]]
    rows: list[dict[str, Any]]
    approx_bytes: int
    expires_at: float


class ResultCache:
    """Volatile memory-only result cache with TTL and byte budget."""

    def __init__(self, max_bytes: int = RESULT_CACHE_MAX_BYTES, ttl_sec: int = RESULT_CACHE_TTL_SEC) -> None:
        self._max_bytes = max_bytes
        self._ttl_sec = ttl_sec
        self._cache: dict[str, CacheEntry] = {}
        self._total_bytes: int = 0

    def _purge_expired(self, now: float) -> None:
        expired_keys = [k for k, entry in self._cache.items() if entry.expires_at <= now]
        for k in expired_keys:
            entry = self._cache.pop(k)
            self._total_bytes -= entry.approx_bytes

    def put(
        self,
        query_id: str,
        snapshot_hash: str,
        columns: list[dict[str, str]],
        rows: list[dict[str, Any]],
    ) -> None:
        """Store rows in volatile memory cache."""
        now = time.time()
        self._purge_expired(now)

        # Estimate row bytes
        approx_bytes = len(str(rows).encode("utf-8")) + 1024

        # Evict oldest if byte budget exceeded
        while self._cache and (self._total_bytes + approx_bytes > self._max_bytes):
            oldest_key = min(self._cache.keys(), key=lambda k: self._cache[k].expires_at)
            removed = self._cache.pop(oldest_key)
            self._total_bytes -= removed.approx_bytes

        if self._total_bytes + approx_bytes <= self._max_bytes:
            entry = CacheEntry(
                query_id=query_id,
                snapshot_hash=snapshot_hash,
                columns=columns,
                rows=rows,
                approx_bytes=approx_bytes,
                expires_at=now + self._ttl_sec,
            )
            self._cache[query_id] = entry
            self._total_bytes += approx_bytes

    def get(self, query_id: str, snapshot_hash: str) -> tuple[list[dict[str, str]], list[dict[str, Any]]] | None:
        """Retrieve cached rows if unexpired and snapshot matches."""
        now = time.time()
        self._purge_expired(now)

        entry = self._cache.get(query_id)
        if entry is None:
            return None

        if entry.expires_at <= now:
            self._cache.pop(query_id, None)
            self._total_bytes -= entry.approx_bytes
            return None

        if entry.snapshot_hash != snapshot_hash:
            # Policy/snapshot changed; cache invalidated (Contract C05)
            self._cache.pop(query_id, None)
            self._total_bytes -= entry.approx_bytes
            return None

        return entry.columns, entry.rows

    def evict(self, query_id: str) -> None:
        """Evict cache entry for query ID."""
        entry = self._cache.pop(query_id, None)
        if entry:
            self._total_bytes -= entry.approx_bytes

    def clear(self) -> None:
        """Clear all cached results."""
        self._cache.clear()
        self._total_bytes = 0


_global_result_cache: ResultCache | None = None


def get_result_cache() -> ResultCache:
    global _global_result_cache
    if _global_result_cache is None:
        _global_result_cache = ResultCache()
    return _global_result_cache
