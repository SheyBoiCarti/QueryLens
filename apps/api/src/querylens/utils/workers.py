"""Worker executor for running synchronous database operations within bounded budgets."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, TypeVar

T = TypeVar("T")

_db_executor: ThreadPoolExecutor | None = None


def get_db_executor(max_workers: int = 8) -> ThreadPoolExecutor:
    """Get or create singleton thread pool executor for DB operations."""
    global _db_executor
    if _db_executor is None:
        _db_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="querylens-db-worker",
        )
    return _db_executor


def shutdown_db_executor(wait: bool = True) -> None:
    """Shutdown database executor pool."""
    global _db_executor
    if _db_executor is not None:
        _db_executor.shutdown(wait=wait)
        _db_executor = None


async def run_db(func: Callable[..., T], *args: Any, timeout_sec: float = 10.0, **kwargs: Any) -> T:
    """Run a synchronous database function inside the bounded executor with timeout."""
    loop = asyncio.get_running_loop()
    executor = get_db_executor()
    task = loop.run_in_executor(executor, lambda: func(*args, **kwargs))
    try:
        return await asyncio.wait_for(task, timeout=timeout_sec)
    except asyncio.TimeoutError as exc:
        raise TimeoutError(f"Database operation timed out after {timeout_sec}s") from exc
