"""Integration tests for Phase 00 Task 00.02 (API health, workers, and logging)."""

import asyncio
import io
import json
import logging
import pytest
from httpx import ASGITransport, AsyncClient

from querylens.config import SecurityProfileError, Settings
from querylens.main import create_app
from querylens.api.health import set_metadata_probe, set_runtime_ready
from querylens.utils.workers import run_db
from querylens.observability.logging import log_event, get_logger, StructuredJsonFormatter


@pytest.mark.asyncio
async def test_health_liveness_and_readiness_probes():
    """Liveness 200 and readiness 503/200 based on metadata probe."""
    app = create_app(Settings(environment="test"))
    set_runtime_ready(True)
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Probe down
        set_metadata_probe(lambda: False)
        live_res = await client.get("/api/v1/health/live")
        assert live_res.status_code == 200
        assert live_res.json()["status"] == "alive"

        ready_res = await client.get("/api/v1/health/ready")
        assert ready_res.status_code == 503
        assert ready_res.json()["status"] == "unready"

        # 2. Probe up
        set_metadata_probe(lambda: True)
        ready_res2 = await client.get("/api/v1/health/ready")
        assert ready_res2.status_code == 200
        assert ready_res2.json()["status"] == "ready"


@pytest.mark.asyncio
async def test_bounded_db_worker_responsiveness():
    """Long blocking work leaves event loop responsive to polling."""
    app = create_app(Settings(environment="test"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        import time

        def slow_blocking_fn():
            time.sleep(0.3)
            return "done"

        # Launch slow work in worker thread
        slow_task = asyncio.create_task(run_db(slow_blocking_fn, timeout_sec=2.0))

        # Health polling should be immediately responsive
        start = asyncio.get_event_loop().time()
        res = await client.get("/api/v1/health/live")
        elapsed = asyncio.get_event_loop().time() - start
        assert res.status_code == 200
        assert elapsed < 0.1  # Fast non-blocking response

        result = await slow_task
        assert result == "done"


def test_production_settings_validation():
    """Missing production secrets/insecure settings fail startup."""
    # Insecure cookie
    with pytest.raises(SecurityProfileError, match="session_cookie_secure"):
        Settings(
            environment="production",
            session_cookie_secure=False,
            session_cookie_name="__Host-querylens_session",
            llm_provider="live",
            credential_keys_file="/path/keys.json",
            credential_active_key_id="key1",
        ).validate_for_production()

    # Fake LLM in production
    with pytest.raises(SecurityProfileError, match="forbids fake LLM provider"):
        Settings(
            environment="production",
            session_cookie_secure=True,
            session_cookie_name="__Host-querylens_session",
            allowed_origins=["https://querylens.example"],
            metadata_database_url="postgresql://localhost/querylens",
            llm_provider="fake",
            credential_keys_file="/path/keys.json",
            credential_active_key_id="key1",
        ).validate_for_production()


def test_structured_logging_allowlist_redaction():
    """Canary cookie/DSN/result/exception parameters never appear in log output."""
    output = io.StringIO()
    handler = logging.StreamHandler(output)
    handler.setFormatter(StructuredJsonFormatter())
    logger = get_logger("querylens_test")
    logger.handlers.clear()
    logger.addHandler(handler)

    canary_dsn = "postgres://admin:SUPER_SECRET_CANARY@host:5432/db"
    canary_cookie = "cookie_token_canary_value_xyz"

    log_event(
        "query_executed",
        level=logging.INFO,
        logger_name="querylens_test",
        run_id="run-1234",
        status="completed",
        row_count=42,
        # Disallowed / sensitive params:
        dsn=canary_dsn,
        cookie=canary_cookie,
        secret_key="my_key",
    )

    log_line = output.getvalue().strip()
    data = json.loads(log_line)

    assert data["event"] == "query_executed"
    assert data["run_id"] == "run-1234"
    assert data["status"] == "completed"
    assert data["row_count"] == 42

    # Verify canaries are NOT present
    assert "dsn" not in data
    assert "cookie" not in data
    assert "secret_key" not in data
    assert "SUPER_SECRET_CANARY" not in log_line
    assert "canary_value_xyz" not in log_line
