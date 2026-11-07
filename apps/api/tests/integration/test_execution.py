"""Integration tests for safe SQL execution and capability token enforcement (Contracts C06, C07)."""

import pytest
import sqlalchemy as sa

from querylens.auth.service import AuthService
from querylens.config import get_settings
from querylens.connections.models import ConnectionCreate
from querylens.connections.service import ConnectionService
from querylens.domain.query import ValidatedQuery
from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
from querylens.execution.executor import ExecutionSecurityError, SafeExecutor
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.sql.policy import validate_and_bound_sql


@pytest.fixture(autouse=True)
def test_db():
    test_eng = sa.create_engine("sqlite:///:memory:")
    set_engine(test_eng)
    create_metadata_tables(test_eng)
    yield test_eng
    drop_metadata_tables(test_eng)
    test_eng.dispose()


def test_executor_rejects_raw_string_and_tampered_token():
    """Executor rejects raw strings and tampered SQL fingerprints (Contract C06)."""
    # 1. Raw string rejected
    with pytest.raises(ExecutionSecurityError, match="Raw strings"):
        SafeExecutor.execute("SELECT 1;")  # type: ignore

    # 2. Tampered fingerprint
    token = ValidatedQuery(
        connection_id="c1",
        engine="postgresql",
        policy_version=1,
        snapshot_hash="hash",
        canonical_sql="SELECT 1;",
        sql_fingerprint="forged_fingerprint_value",
        permitted_identifiers=(),
        max_rows=100,
    )
    with pytest.raises(ExecutionSecurityError, match="fingerprint mismatch"):
        SafeExecutor.execute(token)


def test_live_execution_on_postgresql():
    """Execute ValidatedQuery against live PostgreSQL instance."""
    settings = get_settings()
    if not (settings.postgres_host and settings.postgres_password):
        pytest.skip("No live PostgreSQL credentials configured")

    auth = AuthService()
    user = auth.create_user("exec_tester@example.com", "hash")
    conn_service = ConnectionService()

    conn_res = conn_service.create(
        user["id"],
        ConnectionCreate(
            name="Live PG Exec",
            engine="postgresql",
            host=settings.postgres_host,
            port=int(settings.postgres_port or 28173),
            database=settings.postgres_db or "defaultdb",
            username=settings.postgres_user or "avnadmin",
            password=settings.postgres_password,
            tls_enabled=True,
        ),
    )

    # Simple catalog with 1 table or dual
    snap = CatalogSnapshot(connection_id=conn_res.id, engine="postgresql", tables=[])
    snap.snapshot_hash = snap.compute_hash()

    # Query with literal expression
    token = validate_and_bound_sql("SELECT 100 AS num, 'hello' AS greeting;", conn_res.id, "postgresql", snap, max_rows=10)

    result = SafeExecutor.execute(token)
    assert result.row_count == 1
    assert result.rows[0]["greeting"] == "hello"
    assert result.rows[0]["num"] == "100"
