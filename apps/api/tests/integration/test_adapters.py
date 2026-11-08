"""Integration tests for database adapters and live engine connectivity (Contracts C01, C03)."""

import pytest
import sqlalchemy as sa

from querylens.auth.service import AuthService
from querylens.config import get_settings
from querylens.connections.models import ConnectionCreate, ConnectionUpdate
from querylens.connections.mysql import MySQLAdapter
from querylens.connections.postgres import PostgresAdapter
from querylens.connections.service import ConnectionService
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine


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


def test_connection_crud_and_password_preservation(test_db):
    """ConnectionService creates with AES-256-GCM and preserves secret on partial update."""
    auth = AuthService()
    user = auth.create_user("conn_tester@example.com", "hash")
    service = ConnectionService()

    # 1. Create connection
    created = service.create(
        user["id"],
        ConnectionCreate(
            name="Test PG",
            engine="postgresql",
            host="localhost",
            port=5432,
            database="db",
            username="analyst",
            password="my_original_password",
            tls_enabled=False,
        ),
    )
    assert created.name == "Test PG"

    # 2. Update name without providing password -> password preserved
    updated = service.update(
        user["id"],
        created.id,
        ConnectionUpdate(name="Renamed PG"),
    )
    assert updated.name == "Renamed PG"

    # Verify decrypted password is still original
    from querylens.connections.crypto import decrypt_credential
    from querylens.persistence.tables import connections

    with test_db.connect() as conn:
        row = conn.execute(sa.select(connections).where(connections.c.id == created.id)).fetchone()
        assert row is not None
        decrypted = decrypt_credential(row.encrypted_password, connection_id=created.id)
        assert decrypted == "my_original_password"


def test_mysql_adapter_rejects_mariadb(monkeypatch):
    """MySQL adapter explicitly rejects MariaDB by server identity (Contract C01)."""

    # Mock pymysql connect returning MariaDB version
    class FakeCursor:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def execute(self, q):
            pass

        def fetchone(self):
            return ("10.5.12-MariaDB-1:10.5.12+maria~focal",)

    class FakeConn:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            pass

        def cursor(self):
            return FakeCursor()

        def close(self):
            pass

    monkeypatch.setattr(MySQLAdapter, "connect", lambda *args, **kwargs: FakeConn())
    success, version, msg = MySQLAdapter.test_connection(
            host="127.0.0.1",
            port=3306,
            database="test",
            username="root",
            password="pwd",
            tls_enabled=False,
        )
    assert success is False
    assert "MariaDB is explicitly rejected" in msg


def test_live_aiven_database_connections():
    """Test real live PostgreSQL 18 and MySQL 8.4 instances configured in .env."""
    settings = get_settings()

    # 1. Live PostgreSQL (Aiven)
    if settings.postgres_host and settings.postgres_password:
        success, version, msg = PostgresAdapter.test_connection(
            host=settings.postgres_host,
            port=int(settings.postgres_port or 28173),
            database=settings.postgres_db or "defaultdb",
            username=settings.postgres_user or "avnadmin",
            password=settings.postgres_password,
            tls_enabled=True,
            timeout_sec=10.0,
        )
        assert success is True, f"PostgreSQL live test failed: {msg}"
        assert "PostgreSQL 18" in version

    # 2. Live MySQL (Aiven)
    if settings.mysql_host and settings.mysql_password:
        success, version, msg = MySQLAdapter.test_connection(
            host=settings.mysql_host,
            port=int(settings.mysql_port or 28173),
            database=settings.mysql_db or "defaultdb",
            username=settings.mysql_user or "avnadmin",
            password=settings.mysql_password,
            tls_enabled=True,
            timeout_sec=10.0,
        )
        assert success is True, f"MySQL live test failed: {msg}"
        assert "MySQL 8.4" in version
