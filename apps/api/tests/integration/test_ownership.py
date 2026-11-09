"""Integration tests for the shared workspace and internal legacy ownership guards."""

import pytest
import sqlalchemy as sa
from httpx import ASGITransport, AsyncClient

from querylens.auth.crypto import hash_password
from querylens.auth.ownership import verify_connection_ownership
from querylens.auth.service import AuthService
from querylens.config import Settings
from querylens.main import create_app
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.persistence.tables import connections


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
async def test_shared_workspace_without_login(test_db):
    from querylens.auth.workspace import initialize_workspace

    initialize_workspace()
    app = create_app(Settings(environment="test"))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/api/v1/connections")).status_code == 200
        assert (await client.get("/api/v1/queries/history")).status_code == 200
        assert not client.cookies
        for method, path in (("post", "login"), ("post", "logout"), ("get", "me"), ("get", "csrf")):
            assert (await getattr(client, method)(f"/api/v1/auth/{path}")).status_code == 404


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
