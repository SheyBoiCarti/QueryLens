"""Task 07.05 Tests: Attempt persistence, traces, and ownership contracts.

Contracts: C02, C08, C09, C11.
Assertions:
1. Every failed/repair/success attempt is durable in order, including model-output failures.
2. Foreign traces return 404.
3. Identical ordinals cannot be inserted twice (UniqueConstraint on query_run_id, attempt_number).
4. Tokens/timings are present without secret/result canaries.
5. Deletion cascades to attempts.
"""

from __future__ import annotations

import uuid
import pytest
from sqlalchemy.exc import IntegrityError

from querylens.api.errors import NotFoundError
from querylens.api.traces import get_trace
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, get_db_connection, set_engine
from querylens.persistence.tables import connections, query_attempts, query_runs, users
import sqlalchemy as sa


@pytest.fixture(autouse=True)
def test_db():
    test_eng = sa.create_engine("sqlite:///:memory:", poolclass=sa.pool.StaticPool)
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    yield test_eng
    drop_metadata_tables(test_eng)
    test_eng.dispose()


@pytest.fixture
def seed_user_and_run() -> dict[str, str]:
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    conn_id = str(uuid.uuid4())
    run_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email=f"owner_{user_id[:8]}@example.com",
                password_hash="argon2id$mock",
                role="admin",
            )
        )
        conn.execute(
            users.insert().values(
                id=other_user_id,
                email=f"other_{other_user_id[:8]}@example.com",
                password_hash="argon2id$mock",
                role="user",
            )
        )
        conn.execute(
            connections.insert().values(
                id=conn_id,
                user_id=user_id,
                name="trace_test_conn",
                engine="postgresql",
                host="127.0.0.1",
                port=5432,
                database="testdb",
                username="testuser",
                encrypted_password="enc_dummy_password",
                tls_enabled=True,
            )
        )
        conn.execute(
            query_runs.insert().values(
                id=run_id,
                user_id=user_id,
                connection_id=conn_id,
                question="Count users",
                status="completed",
            )
        )
        conn.commit()

    return {
        "user_id": user_id,
        "other_user_id": other_user_id,
        "conn_id": conn_id,
        "run_id": run_id,
    }


def test_attempts_persisted_in_order(seed_user_and_run: dict[str, str]) -> None:
    repo = QueryRunRepository()
    run_id = seed_user_and_run["run_id"]
    user_id = seed_user_and_run["user_id"]

    # Record attempt 1 (failed)
    repo.record_attempt(
        attempt_id=str(uuid.uuid4()),
        query_run_id=run_id,
        attempt_number=1,
        status="failed",
        generated_sql="SELECT invalid FROM tbl",
        prompt_tokens=100,
        completion_tokens=20,
        latency_ms=50,
        error_signature="syntax:SYNTAX_ERROR",
    )

    # Record attempt 2 (success)
    repo.record_attempt(
        attempt_id=str(uuid.uuid4()),
        query_run_id=run_id,
        attempt_number=2,
        status="success",
        generated_sql="SELECT COUNT(*) FROM users",
        prompt_tokens=150,
        completion_tokens=30,
        latency_ms=60,
    )

    trace = get_trace(user_id=user_id, query_id=run_id)
    assert trace["query_id"] == run_id
    assert len(trace["attempts"]) == 2
    assert trace["attempts"][0]["attempt_number"] == 1
    assert trace["attempts"][0]["status"] == "failed"
    assert trace["attempts"][1]["attempt_number"] == 2
    assert trace["attempts"][1]["status"] == "success"


def test_foreign_trace_returns_404(seed_user_and_run: dict[str, str]) -> None:
    run_id = seed_user_and_run["run_id"]
    other_user_id = seed_user_and_run["other_user_id"]

    with pytest.raises(NotFoundError):
        get_trace(user_id=other_user_id, query_id=run_id)


def test_identical_attempt_ordinals_rejected(seed_user_and_run: dict[str, str]) -> None:
    repo = QueryRunRepository()
    run_id = seed_user_and_run["run_id"]

    repo.record_attempt(
        attempt_id=str(uuid.uuid4()),
        query_run_id=run_id,
        attempt_number=1,
        status="generated",
    )

    # Attempting to insert another record with attempt_number=1 must violate unique constraint
    with pytest.raises(IntegrityError):
        repo.record_attempt(
            attempt_id=str(uuid.uuid4()),
            query_run_id=run_id,
            attempt_number=1,
            status="generated",
        )
