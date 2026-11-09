"""Phase 08 Integration Tests: Query history keyset pagination, deletion, and route precedence.

Contracts: C02, C05, C09.
"""

from __future__ import annotations

import datetime
import uuid
import pytest
from httpx import ASGITransport, AsyncClient
import sqlalchemy as sa

from querylens.auth.dependencies import DEFAULT_DEV_USER
from querylens.auth.workspace import initialize_workspace
from querylens.config import Settings
from querylens.jobs.results import get_result_cache
from querylens.main import create_app
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, get_db_connection, set_engine
from querylens.persistence.tables import connections, query_runs, users


@pytest.fixture
def app_with_test_db():
    test_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    initialize_workspace()

    app = create_app(Settings(environment="test"))
    yield app

    drop_metadata_tables(test_eng)
    test_eng.dispose()


@pytest.mark.asyncio
async def test_history_keyset_pagination_preserves_legacy_runs(app_with_test_db) -> None:
    transport = ASGITransport(app=app_with_test_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        user1 = {"id": DEFAULT_DEV_USER["user_id"]}
        user2 = {"id": "legacy-history-owner"}
        with get_db_connection() as conn:
            conn.execute(users.insert().values(id=user2["id"], email="legacy@example.test", password_hash="disabled"))

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

        # Existing runs from both accounts become shared at startup.
        initialize_workspace()

        # Page 1: limit 2
        res1 = await client.get("/api/v1/queries/history?limit=2")
        assert res1.status_code == 200
        data1 = res1.json()
        assert len(data1["items"]) == 2
        assert data1["next_cursor"] is not None

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

        # Page 3: two more shared runs
        res3 = await client.get(f"/api/v1/queries/history?limit=2&cursor={data2['next_cursor']}")
        assert res3.status_code == 200
        data3 = res3.json()
        assert len(data3["items"]) == 2
        assert data3["next_cursor"] is not None
        res4 = await client.get(f"/api/v1/queries/history?limit=2&cursor={data3['next_cursor']}")
        assert res4.status_code == 200
        data4 = res4.json()
        assert len(data4["items"]) == 1
        assert data4["next_cursor"] is None
        pages = (data1, data2, data3, data4)
        assert {item["id"] for page in pages for item in page["items"]} == {
            *(f"run-u1-{i:02d}" for i in range(5)), *(f"run-u2-{i:02d}" for i in range(2)),
        }


@pytest.mark.asyncio
async def test_shared_history_deletion_without_credentials(app_with_test_db) -> None:
    transport = ASGITransport(app=app_with_test_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        owner = {"id": DEFAULT_DEV_USER["user_id"]}

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

        res_del = await client.delete(
            f"/api/v1/queries/{run_id}",
        )
        assert res_del.status_code == 200
        assert res_del.json()["status"] == "deleted"

        # Cache is evicted
        assert cache.get(run_id) is None


def test_analytics_history_projection_and_shared_delivery(analytics_env, completed_run):
    """The shared workspace delivers validated cached results without login."""
    from querylens.persistence.repositories.history import HistoryRepository
    env = analytics_env
    run = completed_run(origin="saved_question", saved_question_id="deleted-definition", saved_question_version=4,
                        saved_definition_json='{"parameters":{"country":"South Africa"}}')
    response = env.client.get(f"/api/v1/queries/{run['id']}")
    assert response.status_code == 200, response.text
    assert response.json()["rows"] == [{"id": 1}]
    assert response.json()["results_available"] is True
    records, _ = HistoryRepository().list_user_runs(env.owner_id)
    assert len(records) == 1 and records[0]["origin"] == "saved_question"
    assert records[0]["saved_question_id"] == "deleted-definition"
    assert records[0]["saved_question_version"] == 4
    assert "run_context_json" not in records[0] and "saved_definition_json" not in records[0]
    assert "submitted_sql" not in records[0]
    assert HistoryRepository().list_user_runs(env.foreign_id)[0] == []
    # Foreign browser origins are rejected even without session authentication.
    assert env.client.delete(f"/api/v1/queries/{run['id']}", headers={"Origin": "https://foreign.example"}).status_code == 403
    assert env.client.delete(f"/api/v1/queries/{run['id']}", headers=env.headers).status_code == 200
    assert env.cache.get(run["id"]) is None


def test_retention_evicts_rows_with_run_metadata(analytics_env, completed_run):
    from querylens.persistence.retention import run_retention_cleanup
    env = analytics_env
    run = completed_run()
    with env.engine.begin() as conn:
        conn.execute(query_runs.update().where(query_runs.c.id == run["id"]).values(
            created_at=datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=10)))
        assert run_retention_cleanup(conn=conn)["deleted_query_runs"] == 1
    assert env.cache.get(run["id"]) is None
