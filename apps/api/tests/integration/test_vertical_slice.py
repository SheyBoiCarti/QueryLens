"""Integration tests for full vertical-slice natural-language query pipeline (Contracts C02, C08)."""

import asyncio
import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from querylens.auth.crypto import hash_password
from querylens.auth.service import AuthService
from querylens.config import Settings, get_settings
from querylens.connections.models import ConnectionCreate
from querylens.connections.service import ConnectionService
from querylens.llm.fake import get_fake_llm_provider
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
from querylens.main import create_app
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.schema.catalog import CatalogService


@pytest.fixture(autouse=True)
def test_db():
    test_eng = sa.create_engine("sqlite:///:memory:")
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    yield test_eng
    drop_metadata_tables(test_eng)
    test_eng.dispose()


@pytest.mark.asyncio
async def test_full_vertical_slice_workflow(test_db):
    """End-to-end flow: question submission -> async execution -> results polling & clarification."""
    settings = get_settings()
    if not (settings.postgres_host and settings.postgres_password):
        pytest.skip("No live PostgreSQL credentials configured")

    app = create_app(Settings(environment="test"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Create user and login
        auth = AuthService()
        user = auth.create_user("analyst_pipeline@example.com", hash_password("Pass123!"))

        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "analyst_pipeline@example.com", "password": "Pass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        assert login_res.status_code == 200
        csrf_token = login_res.json()["csrf_token"]
        headers = {
            "X-QueryLens-Client": "web",
            "Origin": "http://localhost:5173",
            "X-CSRF-Token": csrf_token,
        }

        # 2. Create PostgreSQL connection
        conn_res = await client.post(
            "/api/v1/connections",
            json={
                "name": "Live PG Pipeline",
                "engine": "postgresql",
                "host": settings.postgres_host,
                "port": int(settings.postgres_port or 28173),
                "database": settings.postgres_db or "defaultdb",
                "username": settings.postgres_user or "avnadmin",
                "password": settings.postgres_password,
                "tls_enabled": True,
            },
            headers=headers,
        )
        assert conn_res.status_code == 201
        conn_id = conn_res.json()["id"]

        # Register fake response for test question
        fake = get_fake_llm_provider()
        fake.register_response(
            "postgresql",
            "get constant values",
            GeneratedCandidate(
                sql="SELECT 42 AS answer, 'querylens' AS app_name;",
                assumptions=["Direct projection"],
                requires_clarification=False,
                usage=LLMUsage(prompt_tokens=50, completion_tokens=15, latency_ms=10),
            ),
        )

        # 3. Submit Query -> 202 Accepted
        post_q = await client.post(
            "/api/v1/queries",
            json={
                "connection_id": conn_id,
                "question": "get constant values",
                "max_rows": 50,
            },
            headers=headers,
        )
        assert post_q.status_code == 202
        query_id = post_q.json()["query_id"]

        # 4. Poll GET /queries/{id} until terminal state
        completed_data = None
        for _ in range(30):
            await asyncio.sleep(0.1)
            get_q = await client.get(f"/api/v1/queries/{query_id}", headers=headers)
            assert get_q.status_code == 200
            data = get_q.json()
            if data["status"] in ("completed", "failed", "rejected", "clarification_required"):
                completed_data = data
                break

        assert completed_data is not None, "Query timed out without reaching terminal state"
        assert completed_data["status"] == "completed"
        assert completed_data["row_count"] == 1
        assert completed_data["rows"][0]["answer"] == "42"
        assert completed_data["rows"][0]["app_name"] == "querylens"

        # 5. Clarification Question Scenario
        post_clarif = await client.post(
            "/api/v1/queries",
            json={
                "connection_id": conn_id,
                "question": "show me the best",
            },
            headers=headers,
        )
        assert post_clarif.status_code == 202
        c_query_id = post_clarif.json()["query_id"]

        # Poll clarification
        clarif_data = None
        for _ in range(30):
            await asyncio.sleep(0.1)
            get_c = await client.get(f"/api/v1/queries/{c_query_id}", headers=headers)
            assert get_c.status_code == 200
            data = get_c.json()
            if data["status"] in ("clarification_required", "completed", "failed"):
                clarif_data = data
                break

        assert clarif_data is not None
        assert clarif_data["status"] == "clarification_required"
        assert "clarification_question" in clarif_data
