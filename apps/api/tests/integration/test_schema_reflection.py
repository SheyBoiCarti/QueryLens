"""Integration tests for schema reflection and visibility enforcement (Contracts C02, C05)."""

import pytest
import sqlalchemy as sa

from querylens.config import get_settings
from querylens.connections.mysql import MySQLAdapter
from querylens.connections.postgres import PostgresAdapter
from querylens.persistence.session import create_metadata_tables, drop_metadata_tables, set_engine
from querylens.schema.inspector import SchemaInspector


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


def test_visibility_policy_empty_yields_empty_catalog():
    """Empty visibility policy yields empty catalog (Contract C05)."""
    # Create test SQLite source database
    src_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    with src_eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE test_table (id INTEGER PRIMARY KEY, secret TEXT);"))

    # Empty allowed tables
    snap = SchemaInspector.reflect_visible_catalog(
        connection_id="c1",
        engine=src_eng,
        engine_name="postgresql",
        allowed_tables={},
    )
    assert len(snap.tables) == 0
    assert snap.snapshot_hash != ""


def test_visibility_policy_filters_forbidden_tables_and_columns():
    """Reflects ONLY selected tables and columns, filtering unselected ones (Contract C05)."""
    src_eng = sa.create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool
    )
    with src_eng.begin() as conn:
        conn.execute(sa.text("CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, salary REAL, ssn TEXT);"))
        conn.execute(sa.text("CREATE TABLE secret_audit (id INTEGER, log TEXT);"))

    # Allow employees with ONLY id and name (exclude salary and ssn)
    allowed = {
        "employees": ["id", "name"],
    }

    snap = SchemaInspector.reflect_visible_catalog(
        connection_id="c1",
        engine=src_eng,
        engine_name="postgresql",
        allowed_tables=allowed,
    )

    assert len(snap.tables) == 1
    t = snap.tables[0]
    assert t.name == "employees"
    col_names = [c.name for c in t.columns]
    assert col_names == ["id", "name"]
    assert "salary" not in col_names
    assert "ssn" not in col_names


def test_live_table_discovery():
    """Discover candidate tables on live Aiven database without sampling rows."""
    settings = get_settings()
    if settings.postgres_host and settings.postgres_password:
        pool = PostgresAdapter.create_pool(
            host=settings.postgres_host,
            port=int(settings.postgres_port or 28173),
            database=settings.postgres_db or "defaultdb",
            username=settings.postgres_user or "avnadmin",
            password=settings.postgres_password,
            tls_enabled=True,
        )
        tables = SchemaInspector.discover_candidate_tables(pool, "postgresql")
        assert isinstance(tables, list)
        pool.dispose()

    if settings.mysql_host and settings.mysql_password:
        my_pool = MySQLAdapter.create_pool(
            host=settings.mysql_host,
            port=int(settings.mysql_port or 28173),
            database=settings.mysql_db or "defaultdb",
            username=settings.mysql_user or "avnadmin",
            password=settings.mysql_password,
            tls_enabled=True,
        )
        my_tables = SchemaInspector.discover_candidate_tables(my_pool, "mysql")
        assert isinstance(my_tables, list)
        my_pool.dispose()
