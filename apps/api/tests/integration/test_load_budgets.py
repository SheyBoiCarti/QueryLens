"""Integration tests for concurrency load budgets, queue saturation, and admission control (Contracts C07, C08, C11)."""

import pytest
from querylens.jobs.admission import (
    AdmissionController,
    AdmissionOverloadError,
    PayloadTooLargeError,
)
from querylens.jobs.runner import graceful_shutdown


def test_concurrency_hard_bounds_and_429():
    controller = AdmissionController(
        global_active_limit=2,
        per_user_active_limit=2,
        per_source_active_limit=2,
    )

    # 1. Acquire up to global limit (2)
    lease1 = controller.acquire(user_id="user-1", connection_id="conn-1")
    lease2 = controller.acquire(user_id="user-2", connection_id="conn-2")

    # 2. Third acquire exceeds global limit (429 with Retry-After)
    with pytest.raises(AdmissionOverloadError) as exc_info:
        controller.acquire(user_id="user-3", connection_id="conn-3")

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers
    assert int(exc_info.value.headers["Retry-After"]) > 0

    # 3. Releasing one lease unblocks subsequent acquisition
    lease1.release()
    lease3 = controller.acquire(user_id="user-3", connection_id="conn-3")
    assert lease3 is not None

    lease2.release()
    lease3.release()


def test_per_user_concurrency_limit():
    controller = AdmissionController(
        global_active_limit=10,
        per_user_active_limit=1,
        per_source_active_limit=10,
    )

    lease = controller.acquire(user_id="user-1", connection_id="conn-1")
    with pytest.raises(AdmissionOverloadError) as exc_info:
        controller.acquire(user_id="user-1", connection_id="conn-2")

    assert exc_info.value.status_code == 429
    lease.release()


def test_per_source_concurrency_limit():
    controller = AdmissionController(
        global_active_limit=10,
        per_user_active_limit=10,
        per_source_active_limit=1,
    )

    lease = controller.acquire(user_id="user-1", connection_id="conn-1")
    with pytest.raises(AdmissionOverloadError) as exc_info:
        controller.acquire(user_id="user-2", connection_id="conn-1")

    assert exc_info.value.status_code == 429
    lease.release()


def test_payload_size_rejection_413():
    controller = AdmissionController()

    # Payload within limits (< 64 KiB)
    lease = controller.acquire(user_id="user-1", connection_id="conn-1", payload_size=1024)
    lease.release()

    # Payload exceeding limit (> 65536 bytes) raises 413
    with pytest.raises(PayloadTooLargeError) as exc_info:
        controller.acquire(user_id="user-1", connection_id="conn-1", payload_size=70000)

    assert exc_info.value.status_code == 413


@pytest.mark.asyncio
async def test_graceful_shutdown_drains_resources():
    res = await graceful_shutdown(deadline_sec=2.0)
    assert res["status"] == "clean"
