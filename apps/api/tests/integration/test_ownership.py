"""Integration tests for ownership boundaries, auth routes, and CSRF (Contracts C02, C05)."""

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from querylens.auth.crypto import hash_password
from querylens.auth.ownership import verify_connection_ownership
from querylens.auth.service import AuthService
from querylens.config import Settings
from querylens.main import create_app
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.persistence.tables import connections, metadata


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


@pytest.mark.asyncio
async def test_auth_endpoints_workflow(test_db):
    """Full login -> me -> csrf -> logout flow with cookie and CSRF handling."""
    # Seed user
    service = AuthService()
    user = service.create_user("analyst@example.com", hash_password("SecretPass123!"))

    app = create_app(Settings(environment="test"))
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Login missing required headers -> 403
        bad_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@example.com", "password": "SecretPass123!"},
        )
        assert bad_res.status_code == 403

        # 2. Login with valid headers
        login_res = await client.post(
            "/api/v1/auth/login",
            json={"email": "analyst@example.com", "password": "SecretPass123!"},
            headers={"X-QueryLens-Client": "web", "Origin": "http://localhost:5173"},
        )
        assert login_res.status_code == 200
        data = login_res.json()
        assert data["user"]["email"] == "analyst@example.com"
        assert "csrf_token" in data
        csrf_token = data["csrf_token"]

        # Cookie was set
        assert "querylens_session" in client.cookies

        # 3. GET /me
        me_res = await client.get("/api/v1/auth/me")
        assert me_res.status_code == 200
        assert me_res.json()["email"] == "analyst@example.com"

        # 4. GET /csrf
        csrf_res = await client.get("/api/v1/auth/csrf")
        assert csrf_res.status_code == 200
        assert csrf_res.json()["csrf_token"] == csrf_token

        # 5. Logout
        logout_res = await client.post("/api/v1/auth/logout")
        assert logout_res.status_code == 200
        assert logout_res.json()["status"] == "logged_out"

        # 6. Replay after logout returns 401
        me_after = await client.get("/api/v1/auth/me")
        assert me_after.status_code == 401


@pytest.mark.asyncio
async def test_two_user_ownership_isolation(test_db):
    """Two-user matrix: user B accessing user A's connection gets 404 (Contract C02)."""
    service = AuthService()
    user_a = service.create_user("usera@example.com", hash_password("passA123"))
    user_b = service.create_user("userb@example.com", hash_password("passB123"))

    # Insert connection owned by User A
    with test_db.begin() as conn:
        conn.execute(
            connections.insert().values(
                id="conn-user-a",
                user_id=user_a["id"],
                name="Postgres Prod",
                engine="postgresql",
                host="pg.internal",
                port=5432,
                database="analytics",
                username="analyst",
                encrypted_password="enc_password",
                tls_enabled=True,
            )
        )

    # User A accesses connection -> success
    owned = verify_connection_ownership("conn-user-a", user_a["id"])
    assert owned["id"] == "conn-user-a"

    # User B accesses connection -> 404 (NOT 403, does not disclose existence)
    from querylens.api.errors import NotFoundError

    with pytest.raises(NotFoundError):
        verify_connection_ownership("conn-user-a", user_b["id"])
