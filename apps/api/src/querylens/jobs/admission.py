"""Job admission controller enforcing global, per-user, and per-source concurrency budgets (Contract C07)."""

from __future__ import annotations

from dataclasses import dataclass
import threading
from typing import Any
from fastapi import HTTPException


class AdmissionOverloadError(HTTPException):
    """Raised when concurrency budgets or queue capacities are exceeded."""

    def __init__(self, detail: str, retry_after: int = 5) -> None:
        super().__init__(
            status_code=429,
            detail=detail,
            headers={"Retry-After": str(retry_after)},
        )
        self.retry_after = retry_after


class PayloadTooLargeError(HTTPException):
    """Raised when SQL or request payload exceeds hard limits (Contract C07)."""

    def __init__(self, detail: str) -> None:
        super().__init__(status_code=413, detail=detail)


@dataclass
class AdmissionLease:
    """Represents an active execution slot lease."""

    user_id: str
    connection_id: str
    controller: AdmissionController
    _released: bool = False

    def release(self) -> None:
        if not self._released:
            self.controller._release(self.user_id, self.connection_id)
            self._released = True

    def __enter__(self) -> AdmissionLease:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()

    async def __aenter__(self) -> AdmissionLease:
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


class AdmissionController:
    """Thread-safe concurrency and queue limit manager."""

    def __init__(
        self,
        global_active_limit: int = 4,
        per_user_active_limit: int = 2,
        per_source_active_limit: int = 1,
        global_waiting_limit: int = 16,
        per_user_waiting_limit: int = 4,
    ) -> None:
        self.global_active_limit = global_active_limit
        self.per_user_active_limit = per_user_active_limit
        self.per_source_active_limit = per_source_active_limit
        self.global_waiting_limit = global_waiting_limit
        self.per_user_waiting_limit = per_user_waiting_limit

        self._lock = threading.Lock()
        self._active_global: int = 0
        self._active_users: dict[str, int] = {}
        self._active_sources: dict[str, int] = {}
        self._waiting_global: int = 0
        self._waiting_users: dict[str, int] = {}

    def acquire(self, user_id: str, connection_id: str, payload_size: int | None = None) -> AdmissionLease:
        """Acquire an active query execution lease or raise 429/413."""
        if payload_size is not None and payload_size > 65536:
            raise PayloadTooLargeError(f"Request payload ({payload_size} bytes) exceeds 65536 byte limit")

        with self._lock:
            # 1. Check waiting limits
            if self._waiting_global >= self.global_waiting_limit:
                raise AdmissionOverloadError("Global queue capacity saturated", retry_after=5)

            user_waiting = self._waiting_users.get(user_id, 0)
            if user_waiting >= self.per_user_waiting_limit:
                raise AdmissionOverloadError("Per-user queue limit reached", retry_after=5)

            # 2. Check active concurrency limits
            if self._active_global >= self.global_active_limit:
                raise AdmissionOverloadError("Global concurrency capacity saturated", retry_after=2)

            user_active = self._active_users.get(user_id, 0)
            if user_active >= self.per_user_active_limit:
                raise AdmissionOverloadError("Per-user concurrency limit reached", retry_after=2)

            source_active = self._active_sources.get(connection_id, 0)
            if source_active >= self.per_source_active_limit:
                raise AdmissionOverloadError("Per-database concurrency limit reached", retry_after=2)

            # 3. Grant lease
            self._active_global += 1
            self._active_users[user_id] = user_active + 1
            self._active_sources[connection_id] = source_active + 1

            return AdmissionLease(user_id=user_id, connection_id=connection_id, controller=self)

    def _release(self, user_id: str, connection_id: str) -> None:
        with self._lock:
            self._active_global = max(0, self._active_global - 1)
            if user_id in self._active_users:
                self._active_users[user_id] = max(0, self._active_users[user_id] - 1)
                if self._active_users[user_id] == 0:
                    del self._active_users[user_id]
            if connection_id in self._active_sources:
                self._active_sources[connection_id] = max(0, self._active_sources[connection_id] - 1)
                if self._active_sources[connection_id] == 0:
                    del self._active_sources[connection_id]


_controller_singleton: AdmissionController | None = None


def get_admission_controller() -> AdmissionController:
    global _controller_singleton
    if _controller_singleton is None:
        _controller_singleton = AdmissionController()
    return _controller_singleton
