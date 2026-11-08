"""Job admission controller enforcing global, per-user, and per-source concurrency budgets (Contract C07)."""

from __future__ import annotations

from dataclasses import dataclass
import asyncio
import time
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

        self._lock = threading.RLock()
        self._active_global: int = 0
        self._active_users: dict[str, int] = {}
        self._active_sources: dict[str, int] = {}
        self._waiting_global: int = 0
        self._waiting_users: dict[str, int] = {}
        self._accepting = True

    def reserve(self, user_id: str, connection_id: str) -> JobReservation:
        """Bound the number of scheduled tasks before the API accepts a run."""
        with self._lock:
            if not self._accepting:
                raise AdmissionOverloadError("Server is shutting down")
            if self._waiting_global >= self.global_waiting_limit:
                raise AdmissionOverloadError("Global queue capacity saturated")
            if self._waiting_users.get(user_id, 0) >= self.per_user_waiting_limit:
                raise AdmissionOverloadError("Per-user queue limit reached")
            self._waiting_global += 1
            self._waiting_users[user_id] = self._waiting_users.get(user_id, 0) + 1
        return JobReservation(user_id, connection_id, self)

    def stop(self) -> None:
        with self._lock:
            self._accepting = False

    def acquire(self, user_id: str, connection_id: str, payload_size: int | None = None) -> AdmissionLease:
        """Acquire an active query execution lease or raise 429/413."""
        if payload_size is not None and payload_size > 65536:
            raise PayloadTooLargeError(f"Request payload ({payload_size} bytes) exceeds 65536 byte limit")

        with self._lock:
            if not self._accepting:
                raise AdmissionOverloadError("Server is shutting down")
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
        from querylens.config import get_settings

        settings = get_settings()
        _controller_singleton = AdmissionController(
            settings.global_active_jobs,
            settings.per_user_active_jobs,
            settings.per_source_active_jobs,
            settings.waiting_jobs_global,
            settings.waiting_jobs_per_user,
        )
    return _controller_singleton


@dataclass
class JobReservation:
    user_id: str
    connection_id: str
    controller: AdmissionController
    state: str = "waiting"
    lease: AdmissionLease | None = None
    work: Any = None
    _deferred: bool = False

    async def activate(self, deadline_sec: float) -> None:
        deadline = time.monotonic() + deadline_sec
        while self.state == "waiting":
            controller = self.controller
            with controller._lock:
                if (
                    controller._accepting
                    and controller._active_global < controller.global_active_limit
                    and controller._active_users.get(self.user_id, 0) < controller.per_user_active_limit
                    and controller._active_sources.get(self.connection_id, 0) < controller.per_source_active_limit
                ):
                    self._remove_waiter()
                    controller._active_global += 1
                    controller._active_users[self.user_id] = controller._active_users.get(self.user_id, 0) + 1
                    controller._active_sources[self.connection_id] = (
                        controller._active_sources.get(self.connection_id, 0) + 1
                    )
                    self.lease = AdmissionLease(self.user_id, self.connection_id, controller)
                    self.state = "active"
                    return
            if time.monotonic() >= deadline:
                raise TimeoutError("Query expired while waiting for execution capacity")
            await asyncio.sleep(0.05)
        raise asyncio.CancelledError()

    def _remove_waiter(self) -> None:
        self.controller._waiting_global -= 1
        count = self.controller._waiting_users.get(self.user_id, 1) - 1
        if count:
            self.controller._waiting_users[self.user_id] = count
        else:
            self.controller._waiting_users.pop(self.user_id, None)

    def release(self) -> None:
        with self.controller._lock:
            if self.work is not None and not self.work.done():
                if not self._deferred:
                    self._deferred = True
                    self.work.add_done_callback(lambda _: self.release())
                return
            if self.state == "waiting":
                self._remove_waiter()
            lease = self.lease
            self.lease = None
            self.state = "released"
        if lease:
            lease.release()


def initialize_admission_controller() -> None:
    """A new application lifespan must not inherit a stopped controller."""
    global _controller_singleton
    if _controller_singleton is not None:
        with _controller_singleton._lock:
            if _controller_singleton._active_global or _controller_singleton._waiting_global:
                raise RuntimeError("Prior runtime still owns source execution leases")
    _controller_singleton = None
