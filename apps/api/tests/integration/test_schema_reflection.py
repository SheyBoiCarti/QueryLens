"""Integration tests for schema reflection and visibility enforcement (Contracts C02, C05)."""

import pytest
import sqlalchemy as sa

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


def test_live_table_discovery(analytics_source):
    """Discover real source tables and reflect only the requested columns."""
    kind, engine = analytics_source
    tables = SchemaInspector.discover_candidate_tables(engine, kind)
    assert any(table.endswith(".ql_analytics_gate") for table in tables)
    namespace = "public" if kind == "postgresql" else engine.url.database
    snapshot = SchemaInspector.reflect_visible_catalog(
        "fixture", engine, kind, {f"{namespace}.ql_analytics_gate": ["id", "day"]},
    )
    assert len(snapshot.tables) == 1
    assert {column.name for column in snapshot.tables[0].columns} == {"id", "day"}


def test_reflection_batches_only_authorized_tables(monkeypatch):
    """Hosted database latency should not multiply by the selected table count."""
    from unittest.mock import Mock

    source = sa.create_engine("sqlite://")
    with source.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE customers (id INTEGER PRIMARY KEY, secret TEXT)")
        conn.exec_driver_sql("CREATE TABLE orders (id INTEGER PRIMARY KEY, customer_id INTEGER REFERENCES customers(id))")
        conn.exec_driver_sql("CREATE TABLE hidden (id INTEGER)")
    with source.connect() as conn:
        inspector = sa.inspect(conn)
        for method in ("get_multi_columns", "get_multi_pk_constraint", "get_multi_foreign_keys", "get_multi_indexes"):
            monkeypatch.setattr(inspector, method, Mock(wraps=getattr(inspector, method)))
        monkeypatch.setattr("querylens.schema.inspector.sa.inspect", lambda connection: inspector)
        snapshot = SchemaInspector.reflect_visible_catalog(
            "fixture", source, "postgresql", {"main.customers": ["id"], "main.orders": []},
        )
        assert {table.name for table in snapshot.tables} == {"customers", "orders"}
        customers = next(table for table in snapshot.tables if table.name == "customers")
        assert [column.name for column in customers.columns] == ["id"]
        orders = next(table for table in snapshot.tables if table.name == "orders")
        assert orders.foreign_keys[0].target_table == "customers"
        for method in ("get_multi_columns", "get_multi_pk_constraint", "get_multi_foreign_keys", "get_multi_indexes"):
            getattr(inspector, method).assert_called_once_with(schema="main", filter_names=["customers", "orders"])
    source.dispose()
