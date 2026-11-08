"""Phase 07 unit tests: Error classification, bounded repair, and diagnostics.

Contracts: C06, C07, C08.
"""

from __future__ import annotations

import uuid
import pytest

from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.llm.fake import FakeLLMProvider
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, get_db_connection, set_engine
from querylens.persistence.tables import connections, users
from querylens.pipeline.orchestrator import run_query_pipeline
from querylens.schema.snapshots import save_snapshot
import sqlalchemy as sa


@pytest.fixture(autouse=True)
def test_db():
    from querylens.jobs.admission import initialize_admission_controller

    initialize_admission_controller()
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    yield test_eng
    drop_metadata_tables(test_eng)
    test_eng.dispose()


@pytest.fixture
def repair_test_env() -> dict[str, str]:
    user_id = str(uuid.uuid4())
    conn_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email=f"repair_{user_id[:8]}@example.com",
                password_hash="argon2id$mock",
                role="admin",
            )
        )
        conn.execute(
            connections.insert().values(
                id=conn_id,
                user_id=user_id,
                name="repair_conn",
                engine="postgresql",
                host="127.0.0.1",
                port=5432,
                database="testdb",
                username="testuser",
                encrypted_password="enc_dummy_password",
                tls_enabled=True,
            )
        )
        conn.commit()

    # Pre-populate catalog snapshot
    test_snapshot = CatalogSnapshot(
        connection_id=conn_id,
        engine="postgres",
        policy_version=1,
        tables=[
            TableMetadata(
                name="customers",
                namespace="public",
                columns=[
                    ColumnMetadata(name="id", canonical_type="integer", db_type="int4", primary_key=True),
                    ColumnMetadata(name="name", canonical_type="string", db_type="varchar"),
                ],
            )
        ],
    )
    test_snapshot.snapshot_hash = test_snapshot.compute_hash()
    save_snapshot(test_snapshot)

    return {"user_id": user_id, "conn_id": conn_id}


@pytest.mark.asyncio
async def test_invalid_then_correct_sql_yields_one_repair(
    repair_test_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = repair_test_env["user_id"]
    conn_id = repair_test_env["conn_id"]
    query_id = str(uuid.uuid4())
    question = "Count total customers"

    repo = QueryRunRepository()
    repo.create(query_id, user_id, conn_id, question)

    # Provider returns syntax error first, then valid query
    fake_llm = FakeLLMProvider()
    fake_llm.register_sequence(
        dialect="postgres",
        question=question,
        candidates=[
            GeneratedCandidate(
                sql="SELECT FORM customers",  # Syntax error on attempt 1
                requires_clarification=False,
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
            ),
            GeneratedCandidate(
                sql="SELECT COUNT(*) AS total FROM customers",  # Valid SQL on attempt 2
                requires_clarification=False,
                usage=LLMUsage(prompt_tokens=120, completion_tokens=25, latency_ms=12),
            ),
        ],
    )

    # Mock SafeExecutor to return a mock result for valid execution
    from querylens.domain.query import QueryResult
    from querylens.execution.executor import SafeExecutor

    mock_result = QueryResult(
        columns=[{"name": "total", "type": "integer", "db_type": "int8"}],
        rows=[{"total": "42"}],
        row_count=1,
        truncated=False,
        execution_time_ms=5,
    )
    monkeypatch.setattr(SafeExecutor, "execute", lambda token, timeout_sec, query_id: mock_result)

    await run_query_pipeline(
        query_id=query_id,
        user_id=user_id,
        connection_id=conn_id,
        question=question,
        provider=fake_llm,
    )

    run = repo.get(query_id, user_id=user_id)
    assert run["status"] == "completed"

    attempts = repo.get_attempts(query_id)
    assert len(attempts) == 2
    assert attempts[0]["attempt_number"] == 1
    assert attempts[0]["generated_sql"] == "SELECT FORM customers"
    assert attempts[1]["attempt_number"] == 2
    assert attempts[1]["generated_sql"] == "SELECT COUNT(*) AS total FROM customers"


@pytest.mark.asyncio
async def test_repeated_invalid_sql_stops_after_max_repairs(
    repair_test_env: dict[str, str],
) -> None:
    user_id = repair_test_env["user_id"]
    conn_id = repair_test_env["conn_id"]
    query_id = str(uuid.uuid4())
    question = "Get invalid items"

    repo = QueryRunRepository()
    repo.create(query_id, user_id, conn_id, question)

    # Return different invalid queries to avoid loop detector, testing max attempts bound
    fake_llm = FakeLLMProvider()
    fake_llm.register_sequence(
        dialect="postgres",
        question=question,
        candidates=[
            GeneratedCandidate(
                sql="SELECT FORM customers",  # Invalid 1
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
            ),
            GeneratedCandidate(
                sql="SELECT WHRE id = 1 FROM customers",  # Invalid 2
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
            ),
            GeneratedCandidate(
                sql="SELECT GROUP BY customers",  # Invalid 3
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
            ),
        ],
    )

    await run_query_pipeline(
        query_id=query_id,
        user_id=user_id,
        connection_id=conn_id,
        question=question,
        provider=fake_llm,
    )

    run = repo.get(query_id, user_id=user_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "MAX_ATTEMPTS_EXCEEDED"

    attempts = repo.get_attempts(query_id)
    assert len(attempts) == 3


@pytest.mark.asyncio
async def test_policy_violation_triggers_zero_repairs(
    repair_test_env: dict[str, str],
) -> None:
    user_id = repair_test_env["user_id"]
    conn_id = repair_test_env["conn_id"]
    query_id = str(uuid.uuid4())
    question = "Drop table users"

    repo = QueryRunRepository()
    repo.create(query_id, user_id, conn_id, question)

    fake_llm = FakeLLMProvider()
    fake_llm.register_response(
        dialect="postgres",
        question=question,
        candidate=GeneratedCandidate(
            sql="DROP TABLE customers",
            usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
        ),
    )

    await run_query_pipeline(
        query_id=query_id,
        user_id=user_id,
        connection_id=conn_id,
        question=question,
        provider=fake_llm,
    )

    run = repo.get(query_id, user_id=user_id)
    assert run["status"] == "rejected"
    assert run["error_code"] == "POLICY_VIOLATION"

    attempts = repo.get_attempts(query_id)
    # Exactly one attempt, no repairs!
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_repeated_candidate_fails_repair_stalled(
    repair_test_env: dict[str, str],
) -> None:
    user_id = repair_test_env["user_id"]
    conn_id = repair_test_env["conn_id"]
    query_id = str(uuid.uuid4())
    question = "Stalled query test"

    repo = QueryRunRepository()
    repo.create(query_id, user_id, conn_id, question)

    # Return identical SQL on repair
    fake_llm = FakeLLMProvider()
    fake_llm.register_sequence(
        dialect="postgres",
        question=question,
        candidates=[
            GeneratedCandidate(
                sql="SELECT FORM customers",
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
            ),
            GeneratedCandidate(
                sql="SELECT   FORM   customers",  # Whitespace variant of identical query
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
            ),
        ],
    )

    await run_query_pipeline(
        query_id=query_id,
        user_id=user_id,
        connection_id=conn_id,
        question=question,
        provider=fake_llm,
    )

    run = repo.get(query_id, user_id=user_id)
    assert run["status"] == "failed"
    assert run["error_code"] == "REPAIR_STALLED"
