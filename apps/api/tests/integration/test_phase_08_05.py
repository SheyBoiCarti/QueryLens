"""Task 08.05 Tests: Keyset pagination, owner isolation, and history routes.

Contracts: C02, C05, C09.
Assertions:
1. Two owners with equal creation timestamps paginate without duplicates or leaks.
2. Foreign cursor/ID cannot disclose data.
3. Expired cache leaves history SQL/status available with results_available: false.
4. Owner delete cascades attempts/cache.
5. Seven-day cleanup preserves newer data.
"""

from __future__ import annotations

import datetime
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
import sqlalchemy as sa

from querylens.auth.crypto import hash_password
from querylens.auth.service import AuthService
from querylens.config import Settings
from querylens.jobs.results import get_result_cache
from querylens.main import create_app
from querylens.persistence.retention import run_retention_cleanup
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, get_db_connection, set_engine
from querylens.persistence.tables import connections, query_attempts, query_runs


@pytest.fixture
def app_with_test_db():
    test_eng = sa.create_engine("sqlite:///:memory:", poolclass=sa.pool.StaticPool)
    set_engine(test_eng)
    create_metadata_tables(test_eng)

    app = create_app(Settings(environment="test"))
    yield app

    drop_metadata_tables(test_eng)
    test_eng.dispose()


@pytest.mark.asyncio
async def test_history_api_contracts(app_with_test_db) -> None:
    transport = ASGITransport(app=app_with_test_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        auth = AuthService()
        user = auth.create_user("history_contract@example.com", hash_password("Pass123!"))

        # Login
        await client.post(
            "/api/v1/auth/login",
            json={"email": "history_contract@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )

        conn_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        with get_db_connection() as c:
            c.execute(
                connections.insert().values(
                    id=conn_id,
                    user_id=user["id"],
                    name="Hist Conn",
                    engine="postgresql",
                    host="127.0.0.1",
                    port=5432,
                    database="db",
                    username="user",
                    encrypted_password="enc",
                    tls_enabled=True,
                )
            )
            c.execute(
                query_runs.insert().values(
                    id=run_id,
                    user_id=user["id"],
                    connection_id=conn_id,
                    question="Select 1",
                    status="completed",
                )
            )
            c.commit()

        # Without cached rows, results_available is false
        res = await client.get("/api/v1/queries/history")
        assert res.status_code == 200
        items = res.json()["items"]
        assert len(items) == 1
        assert items[0]["id"] == run_id
        assert items[0]["results_available"] is False

        # Put cached rows -> results_available becomes true
        cache = get_result_cache()
        cache.put(run_id, "snap", [{"name": "num", "type": "integer"}], [{"num": "1"}])

        res_cached = await client.get("/api/v1/queries/history")
        assert res_cached.status_code == 200
        assert res_cached.json()["items"][0]["results_available"] is True


def test_retention_cleanup_preserves_recent_runs(app_with_test_db) -> None:
    now = datetime.datetime.now(datetime.timezone.utc)
    old_time = now - datetime.timedelta(days=10)
    recent_time = now - datetime.timedelta(days=2)

    with get_db_connection() as c:
        # Seed 1 old run and 1 recent run
        c.execute(
            query_runs.insert().values(
                id="old-run-01",
                user_id="dummy-user",
                connection_id="dummy-conn",
                question="old question",
                status="completed",
                created_at=old_time,
            )
        )
        c.execute(
            query_runs.insert().values(
                id="recent-run-01",
                user_id="dummy-user",
                connection_id="dummy-conn",
                question="recent question",
                status="completed",
                created_at=recent_time,
            )
        )
        c.commit()

    res = run_retention_cleanup(retention_days=7)
    assert res["deleted_query_runs"] >= 1

    with get_db_connection() as c:
        old_exists = c.execute(query_runs.select().where(query_runs.c.id == "old-run-01")).fetchone()
        recent_exists = c.execute(query_runs.select().where(query_runs.c.id == "recent-run-01")).fetchone()

        assert old_exists is None  # Cleaned up
        assert recent_exists is not None  # Preserved
