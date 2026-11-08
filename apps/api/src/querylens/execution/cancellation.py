"""Cancellation bound to a live execution lease, including connect/register races."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
import threading
import socket

from querylens.observability.logging import log_event


@dataclass(frozen=True)
class ExecutionHandle:
    query_id: str
    connection_id: str
    engine: str
    backend_pid: int
    lease_id: str
    cancel: Callable[[], None] | None = field(default=None, compare=False, repr=False)
    terminate: Callable[[], None] | None = field(default=None, compare=False, repr=False)
    operation_lock: threading.RLock = field(default_factory=threading.RLock, compare=False, repr=False)


_registry_lock = threading.RLock()
_active_handles: dict[str, ExecutionHandle] = {}
_cancel_events: dict[str, threading.Event] = {}


def prepare_execution(query_id: str) -> threading.Event:
    with _registry_lock:
        return _cancel_events.setdefault(query_id, threading.Event())


def check_cancelled(query_id: str | None) -> None:
    if query_id and prepare_execution(query_id).is_set():
        raise InterruptedError("Source execution cancelled")


def register_execution(handle: ExecutionHandle) -> None:
    with _registry_lock:
        check_cancelled(handle.query_id)
        _active_handles[handle.query_id] = handle


def unregister_execution(query_id: str) -> None:
    with _registry_lock:
        handle = _active_handles.get(query_id)
    if handle:
        with handle.operation_lock:
            with _registry_lock:
                if _active_handles.get(query_id) is handle:
                    _active_handles.pop(query_id, None)


def forget_execution(query_id: str) -> None:
    with _registry_lock:
        _cancel_events.pop(query_id, None)


def get_active_execution(query_id: str) -> ExecutionHandle | None:
    with _registry_lock:
        return _active_handles.get(query_id)


def signal_cancel(query_id: str) -> None:
    prepare_execution(query_id).set()


def cancel_active_source_query(handle: ExecutionHandle) -> bool:
    # Hold only this execution's lease during control I/O. Other workers and
    # socket interruption must remain available if a cancel connection stalls.
    with handle.operation_lock:
        with _registry_lock:
            if _active_handles.get(handle.query_id) is not handle or not handle.cancel:
                return False
        try:
            handle.cancel()
            return True
        except Exception:
            log_event("source_cancel_failed", query_id=handle.query_id, engine=handle.engine)
            return False


def cancel_source(query_id: str) -> None:
    signal_cancel(query_id)
    handle = get_active_execution(query_id)
    if handle:
        cancel_active_source_query(handle)


def terminate_source(query_id: str) -> None:
    """Interrupt a stalled source socket after graceful cancellation expires."""
    with _registry_lock:
        handle = _active_handles.get(query_id)
        if handle and handle.terminate:
            try:
                handle.terminate()
            except Exception:
                pass  # A concurrently finished/closed socket is already interrupted.


def shutdown_source_socket(connection, engine: str) -> None:
    if engine == "mysql":
        connection._sock.shutdown(socket.SHUT_RDWR)
    else:
        # Borrow the native handle without taking ownership of libpq's socket.
        borrowed = socket.socket(fileno=connection.fileno())
        try:
            borrowed.shutdown(socket.SHUT_RDWR)
        finally:
            borrowed.detach()
