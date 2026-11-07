"""Phase 08 Integration Tests: Query history keyset pagination, deletion, and route precedence.

Contracts: C02, C05, C09.
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
from querylens.persistence.repositories.history import HistoryRepository
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, get_db_connection, set_engine
from querylens.persistence.tables import connections, query_runs


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
async def test_history_keyset_pagination_and_ownership(app_with_test_db) -> None:
    transport = ASGITransport(app=app_with_test_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        auth = AuthService()
        user1 = auth.create_user("user1_hist@example.com", hash_password("Pass123!"))
        user2 = auth.create_user("user2_hist@example.com", hash_password("Pass123!"))

        conn_id = str(uuid.uuid4())
        with get_db_connection() as c:
            c.execute(
                connections.insert().values(
                    id=conn_id,
                    user_id=user1["id"],
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
            c.commit()

        # Seed 5 runs for user 1 with fixed timestamps
        fixed_time = datetime.datetime.now(datetime.timezone.utc)
        user1_run_ids = []
        with get_db_connection() as c:
            for i in range(5):
                rid = f"run-u1-{i:02d}"
                user1_run_ids.append(rid)
                c.execute(
                    query_runs.insert().values(
                        id=rid,
                        user_id=user1["id"],
                        connection_id=conn_id,
                        question=f"Question {i}",
                        status="completed",
                        created_at=fixed_time,
                    )
                )
            # Seed 2 runs for user 2 with identical timestamp
            for i in range(2):
                c.execute(
                    query_runs.insert().values(
                        id=f"run-u2-{i:02d}",
                        user_id=user2["id"],
                        connection_id=conn_id,
                        question=f"User 2 Question {i}",
                        status="completed",
                        created_at=fixed_time,
                    )
                )
            c.commit()

        # Login as user 1
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "user1_hist@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        assert login_res.status_code == 200

        # Page 1: limit 2
        res1 = await client.get("/api/v1/queries/history?limit=2")
        assert res1.status_code == 200
        data1 = res1.json()
        assert len(data1["items"]) == 2
        assert data1["next_cursor"] is not None

        # Verify no foreign runs from user 2 appear
        for item in data1["items"]:
            assert item["id"].startswith("run-u1-")

        # Page 2: using cursor
        res2 = await client.get(f"/api/v1/queries/history?limit=2&cursor={data1['next_cursor']}")
        assert res2.status_code == 200
        data2 = res2.json()
        assert len(data2["items"]) == 2
        assert data2["next_cursor"] is not None

        # Ensure no duplicates between page 1 and page 2
        p1_ids = {item["id"] for item in data1["items"]}
        p2_ids = {item["id"] for item in data2["items"]}
        assert p1_ids.isdisjoint(p2_ids)

        # Page 3: last item
        res3 = await client.get(f"/api/v1/queries/history?limit=2&cursor={data2['next_cursor']}")
        assert res3.status_code == 200
        data3 = res3.json()
        assert len(data3["items"]) == 1
        assert data3["next_cursor"] is None


@pytest.mark.asyncio
async def test_owner_deletion_and_foreign_rejection(app_with_test_db) -> None:
    transport = ASGITransport(app=app_with_test_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        auth = AuthService()
        owner = auth.create_user("owner_del@example.com", hash_password("Pass123!"))
        foreign_user = auth.create_user("foreign_del@example.com", hash_password("Pass123!"))

        # Login owner
        res_login = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner_del@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        csrf_token = res_login.json()["csrf_token"]

        conn_id = str(uuid.uuid4())
        run_id = str(uuid.uuid4())
        with get_db_connection() as c:
            c.execute(
                connections.insert().values(
                    id=conn_id,
                    user_id=owner["id"],
                    name="Owner Conn",
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
                    user_id=owner["id"],
                    connection_id=conn_id,
                    question="Delete me",
                    status="completed",
                )
            )
            c.commit()

        # Cache row
        cache = get_result_cache()
        cache.put(run_id, "snap", [{"name": "col", "type": "string"}], [{"col": "val"}])
        assert cache.get(run_id) is not None

        # Foreign user tries to delete -> 404
        login_foreign = await client.post(
            "/api/v1/auth/login",
            json={"email": "foreign_del@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        foreign_csrf = login_foreign.json()["csrf_token"]

        res_foreign_del = await client.delete(
            f"/api/v1/queries/{run_id}",
            headers={"X-CSRF-Token": foreign_csrf, "Origin": "http://localhost:5173"},
        )
        assert res_foreign_del.status_code == 404

        # Owner re-authenticates and deletes
        await client.post(
            "/api/v1/auth/login",
            json={"email": "owner_del@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        res_csrf = await client.get("/api/v1/auth/csrf")
        owner_csrf = res_csrf.json()["csrf_token"]

        res_del = await client.delete(
            f"/api/v1/queries/{run_id}",
            headers={"X-CSRF-Token": owner_csrf, "Origin": "http://localhost:5173"},
        )
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "deleted"

        # Cache is evicted
        assert cache.get(run_id) is None
