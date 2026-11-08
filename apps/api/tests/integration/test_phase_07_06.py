"""Task 07.06 Tests: Cancellation, leases, and recoverability contracts.

Contracts: C02, C03, C07, C08.
Assertions:
1. Cancel during nonterminal stages reaches cancelled after cleanup.
2. Completion/cancel race cannot overwrite terminal state.
3. Foreign cancel is 404.
4. Restart marks every nonterminal run interrupted (PROCESS_INTERRUPTED).
"""

from __future__ import annotations

import uuid
import pytest

from querylens.api.errors import NotFoundError
from querylens.jobs.cancel import request_cancel
from querylens.jobs.state import reconcile_interrupted_runs
from querylens.persistence.repositories.query_runs import NONTERMINAL_STATES, QueryRunRepository
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, get_db_connection, set_engine
from querylens.persistence.tables import connections, users
import sqlalchemy as sa


@pytest.fixture(autouse=True)
def test_db():
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    yield test_eng
    drop_metadata_tables(test_eng)
    test_eng.dispose()


@pytest.fixture
def setup_cancellation_data() -> dict[str, str]:
    user_id = str(uuid.uuid4())
    other_user_id = str(uuid.uuid4())
    conn_id = str(uuid.uuid4())

    with get_db_connection() as conn:
        conn.execute(
            users.insert().values(
                id=user_id,
                email=f"cancel_{user_id[:8]}@example.com",
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
                name="cancel_test_conn",
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


async def test_foreign_cancel_returns_404(setup_cancellation_data: dict[str, str]) -> None:
    repo = QueryRunRepository()
    user_id = setup_cancellation_data["user_id"]
    other_user_id = setup_cancellation_data["other_user_id"]
    conn_id = setup_cancellation_data["conn_id"]

    run_id = str(uuid.uuid4())
    repo.create(run_id, user_id, conn_id, "test question")

    with pytest.raises(NotFoundError):
        await request_cancel(run_id, other_user_id)


async def test_cancel_nonterminal_run(setup_cancellation_data: dict[str, str]) -> None:
    repo = QueryRunRepository()
    user_id = setup_cancellation_data["user_id"]
    conn_id = setup_cancellation_data["conn_id"]

    for stage in ["queued", "generating", "validating", "executing", "repairing"]:
        run_id = str(uuid.uuid4())
        repo.create(run_id, user_id, conn_id, "test question")
        repo.update_state(run_id, stage)

        res = await request_cancel(run_id, user_id)
        assert res["status"] == "cancelled"

        updated = repo.get(run_id, user_id=user_id)
        assert updated["status"] == "cancelled"


async def test_terminal_states_cannot_be_overwritten(setup_cancellation_data: dict[str, str]) -> None:
    repo = QueryRunRepository()
    user_id = setup_cancellation_data["user_id"]
    conn_id = setup_cancellation_data["conn_id"]

    run_id = str(uuid.uuid4())
    repo.create(run_id, user_id, conn_id, "completed question")
    repo.update_state(run_id, "completed")

    res = await request_cancel(run_id, user_id)
    assert res["status"] == "completed"

    updated = repo.get(run_id, user_id=user_id)
    assert updated["status"] == "completed"


def test_restart_reconciliation_marks_all_nonterminal_interrupted(setup_cancellation_data: dict[str, str]) -> None:
    repo = QueryRunRepository()
    user_id = setup_cancellation_data["user_id"]
    conn_id = setup_cancellation_data["conn_id"]

    created_ids = []
    for stage in NONTERMINAL_STATES:
        run_id = str(uuid.uuid4())
        repo.create(run_id, user_id, conn_id, f"test {stage}")
        repo.update_state(run_id, stage)
        created_ids.append(run_id)

    count = reconcile_interrupted_runs()
    assert count >= len(NONTERMINAL_STATES)

    for rid in created_ids:
        r = repo.get(rid, user_id=user_id)
        assert r["status"] == "interrupted"
        assert r["error_code"] == "PROCESS_INTERRUPTED"
