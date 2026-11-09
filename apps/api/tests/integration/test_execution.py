"""Integration tests for safe SQL execution and capability token enforcement (Contracts C06, C07)."""

import pytest
import sqlalchemy as sa

from querylens.domain.query import ValidatedQuery
from querylens.execution.executor import ExecutionSecurityError, SafeExecutor
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.sql.policy import validate_and_bound_sql


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


def test_live_execution_on_source(analytics_source_env):
    """SafeExecutor checks metadata and executes real bounded source results."""
    env = analytics_source_env
    token = validate_and_bound_sql(
        "SELECT 100 AS num, 'hello' AS greeting", env.connection_id, env.snapshot.engine, env.snapshot, max_rows=10,
    )
    result = SafeExecutor.execute(token)
    assert result.row_count == 1
    assert result.rows[0]["greeting"] == "hello"
    assert result.rows[0]["num"] == "100"
