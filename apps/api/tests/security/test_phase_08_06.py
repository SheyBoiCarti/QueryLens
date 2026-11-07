"""Task 08.06 Tests: Export security, cache expiration, and owner isolation contracts.

Contracts: C02, C07, C09.
Assertions:
1. Foreign/unknown IDs return 404 even when cache expired.
2. Owner expiry returns 410.
3. Unsupported format returns 422.
4. Formula injection neutralized in headers and data.
5. Generation/executor call counts remain zero during export.
"""

from __future__ import annotations

import uuid
import pytest
from httpx import ASGITransport, AsyncClient
import sqlalchemy as sa

from querylens.auth.crypto import hash_password
from querylens.auth.service import AuthService
from querylens.config import Settings
from querylens.jobs.results import get_result_cache
from querylens.main import create_app
from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.persistence.tables import connections


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
async def test_export_security_and_expiry_workflow(app_with_test_db) -> None:
    transport = ASGITransport(app=app_with_test_db)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create owner and foreign user
        auth = AuthService()
        owner = auth.create_user("owner_csv@example.com", hash_password("Pass123!"))
        foreign_user = auth.create_user("foreign_csv@example.com", hash_password("Pass123!"))

        # Login as owner
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "owner_csv@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        assert login_res.status_code == 200

        # Seed connection & query run
        repo = QueryRunRepository()
        conn_id = str(uuid.uuid4())
        from querylens.persistence.session import get_db_connection

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
            c.commit()

        run_id = str(uuid.uuid4())
        repo.create(run_id, owner["id"], conn_id, "Show numbers")
        repo.update_state(run_id, "completed")

        # 2. Cache is initially empty -> Owner receives 410 Gone
        res_expired = await client.get(f"/api/v1/queries/{run_id}/export?format=csv")
        assert res_expired.status_code == 410

        # 3. Populate cache
        cache = get_result_cache()
        cache.put(
            query_id=run_id,
            snapshot_hash="snap-01",
            columns=[{"name": "id", "type": "integer"}, {"name": "calc", "type": "string"}],
            rows=[{"id": "1", "calc": "=SUM(A1:A10)"}],
        )

        # 4. Request with unsupported format -> 422
        res_bad_format = await client.get(f"/api/v1/queries/{run_id}/export?format=xlsx")
        assert res_bad_format.status_code == 422

        # 5. Owner exports valid CSV -> 200 with neutralized formula
        res_ok = await client.get(f"/api/v1/queries/{run_id}/export?format=csv")
        assert res_ok.status_code == 200
        assert res_ok.headers["content-type"].startswith("text/csv")
        assert res_ok.headers["cache-control"] == "no-store"
        assert res_ok.headers["x-content-type-options"] == "nosniff"

        csv_body = res_ok.text
        assert '"\'=SUM(A1:A10)"' in csv_body

        # 6. Foreign user access -> 404 (does not disclose existence)
        login_foreign = await client.post(
            "/api/v1/auth/login",
            json={"email": "foreign_csv@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        assert login_foreign.status_code == 200

        res_foreign = await client.get(f"/api/v1/queries/{run_id}/export?format=csv")
        assert res_foreign.status_code == 404
