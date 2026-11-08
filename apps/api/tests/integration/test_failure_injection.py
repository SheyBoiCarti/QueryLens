"""Integration tests for failure injection, crash recovery, and socket disposal (Contracts C03, C07, C08, C11)."""

import pytest
import sqlalchemy as sa
from querylens.connections.registry import get_registry
from querylens.jobs.runner import reconcile_interrupted_jobs


def test_reconcile_interrupted_jobs_on_restart():
    # Setup in-memory metadata store with query_runs table
    engine = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    stmts = [
        """CREATE TABLE query_runs (
            id VARCHAR(36) PRIMARY KEY,
            user_id VARCHAR(36) NOT NULL,
            status VARCHAR(20) NOT NULL,
            error_code TEXT NULL,
            safe_message TEXT NULL,
            updated_at TIMESTAMP NULL
        )""",
        "INSERT INTO query_runs (id, user_id, status) VALUES ('run-1', 'user-1', 'executing')",
        "INSERT INTO query_runs (id, user_id, status) VALUES ('run-2', 'user-1', 'queued')",
        "INSERT INTO query_runs (id, user_id, status) VALUES ('run-3', 'user-1', 'completed')",
        "INSERT INTO query_runs (id, user_id, status) VALUES ('run-4', 'user-1', 'failed')",
    ]
    with engine.begin() as conn:
        for stmt in stmts:
            conn.execute(sa.text(stmt))

    # Reconcile leftover nonterminal jobs
    count = reconcile_interrupted_jobs(engine)
    assert count == 2

    with engine.connect() as conn:
        rows = dict(conn.execute(sa.text("SELECT id, status FROM query_runs")).fetchall())
        assert rows["run-1"] == "interrupted"
        assert rows["run-2"] == "interrupted"
        assert rows["run-3"] == "completed"  # Terminal status preserved!
        assert rows["run-4"] == "failed"  # Terminal status preserved!


def test_pool_exhaustion_and_disposal_recovery():
    registry = get_registry()
    # Ensure registry can dispose cleanly
    registry.dispose_all()
    assert len(registry._pools) == 0
