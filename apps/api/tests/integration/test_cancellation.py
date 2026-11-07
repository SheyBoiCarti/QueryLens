"""Phase 07 integration tests: Cancellation, process reconciliation, and handle cleanup.

Contracts: C02, C03, C07, C08.
"""

from __future__ import annotations

import uuid
import pytest

from querylens.api.errors import NotFoundError
from querylens.execution.cancellation import (
    ExecutionHandle,
    cancel_active_source_query,
    get_active_execution,
    register_execution,
    unregister_execution,
)
from querylens.jobs.cancel import request_cancel
from querylens.jobs.state import reconcile_interrupted_runs
from querylens.persistence.repositories.query_runs import NONTERMINAL_STATES, QueryRunRepository
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, get_db_connection, set_engine
from querylens.persistence.tables import connections, query_runs, users
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
def setup_cancel_env() -> dict[str, str]:
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    conn_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email=f"cancel_user_{user_id[:8]}@example.com",
                password_hash="argon2id$mock",
                role="admin",
            )
        )
        conn.execute(
            users.insert().values(
                id=other_user_id,
                email=f"foreign_{other_user_id[:8]}@example.com",
                password_hash="argon2id$mock",
                role="user",
            )
        )
        conn.execute(
            connections.insert().values(
                id=conn_id,
                user_id=user_id,
                name="cancellation_env_conn",
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

    return {"user_id": user_id, "other_user_id": other_user_id, "conn_id": conn_id}


def test_cancel_active_execution_handle_registry() -> None:
    query_id = str(uuid.uuid4())
    handle = ExecutionHandle(
        query_id=query_id,
        connection_id="conn-1",
        engine="postgres",
        backend_pid=12345,
        lease_id="lease-1",
    )

    register_execution(handle)
    assert get_active_execution(query_id) == handle

    unregister_execution(query_id)
    assert get_active_execution(query_id) is None


def test_cancel_nonterminal_queries(setup_cancel_env: dict[str, str]) -> None:
    repo = QueryRunRepository()
    user_id = setup_cancel_env["user_id"]
    conn_id = setup_cancel_env["conn_id"]

    for state in ["queued", "generating", "validating", "executing", "repairing"]:
        qid = str(uuid.uuid4())
        repo.create(qid, user_id, conn_id, f"Query in {state}")
        repo.update_state(qid, state)

        res = request_cancel(qid, user_id)
        assert res["status"] == "cancelled"

        run = repo.get(qid, user_id=user_id)
        assert run["status"] == "cancelled"


def test_cancel_foreign_query_fails_404(setup_cancel_env: dict[str, str]) -> None:
    repo = QueryRunRepository()
    user_id = setup_cancel_env["user_id"]
    other_user = setup_cancel_env["other_user_id"]
    conn_id = setup_cancel_env["conn_id"]

    qid = str(uuid.uuid4())
    repo.create(qid, user_id, conn_id, "Owner query")

    with pytest.raises(NotFoundError):
        request_cancel(qid, other_user)


def test_startup_reconciliation_marks_all_nonterminal_interrupted(
    setup_cancel_env: dict[str, str],
) -> None:
    repo = QueryRunRepository()
    user_id = setup_cancel_env["user_id"]
    conn_id = setup_cancel_env["conn_id"]

    query_ids = []
    for state in NONTERMINAL_STATES:
        qid = str(uuid.uuid4())
        repo.create(qid, user_id, conn_id, f"Running {state}")
        repo.update_state(qid, state)
        query_ids.append(qid)

    count = reconcile_interrupted_runs()
    assert count >= len(NONTERMINAL_STATES)

    for qid in query_ids:
        run = repo.get(qid, user_id=user_id)
        assert run["status"] == "interrupted"
        assert run["error_code"] == "PROCESS_INTERRUPTED"
