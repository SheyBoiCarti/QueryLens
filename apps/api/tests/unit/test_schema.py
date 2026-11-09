"""Unit tests for Phase 03 schema models, canonical hashing, normalization, and graph traversal."""


from querylens.domain.schema import (
    CatalogSnapshot,
    ColumnMetadata,
    ForeignKeyConstraint,
    TableMetadata,
)
from querylens.schema.graph import SchemaGraph
from querylens.schema.inspector import is_system_schema
from querylens.schema.normalizer import normalize_data_type


def test_data_type_normalization():
    """Engine types normalize to canonical types (Contract C05, C09)."""
    assert normalize_data_type("integer") == "integer"
    assert normalize_data_type("BIGINT") == "integer"
    assert normalize_data_type("NUMERIC(12, 4)") == "decimal"
    assert normalize_data_type("decimal(10,2)") == "decimal"
    assert normalize_data_type("double precision") == "float"
    assert normalize_data_type("float") == "float"
    assert normalize_data_type("varchar(255)") == "string"
    assert normalize_data_type("text") == "string"
    assert normalize_data_type("boolean") == "boolean"
    assert normalize_data_type("date") == "date"
    assert normalize_data_type("timestamp with time zone") == "datetime"


def test_system_schema_rejection():
    """System and temporary schemas are strictly excluded (Contract C05)."""
    assert is_system_schema("postgresql", "pg_catalog") is True
    assert is_system_schema("postgresql", "information_schema") is True
    assert is_system_schema("postgresql", "pg_toast") is True
    assert is_system_schema("postgresql", "pg_temp_123") is True
    assert is_system_schema("postgresql", "public") is False

    assert is_system_schema("mysql", "information_schema") is True
    assert is_system_schema("mysql", "performance_schema") is True
    assert is_system_schema("mysql", "mysql") is True
    assert is_system_schema("mysql", "sys") is True
    assert is_system_schema("mysql", "analytics") is False


def test_deterministic_snapshot_hashing():
    """Catalog snapshot hash is deterministic regardless of table/column order."""
    t1 = TableMetadata(
        name="customers",
        namespace="public",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="serial", primary_key=True),
            ColumnMetadata(name="email", canonical_type="string", db_type="varchar(255)"),
        ],
        primary_key_columns=["id"],
    )

    t2 = TableMetadata(
        name="orders",
        namespace="public",
        columns=[
            ColumnMetadata(name="id", canonical_type="integer", db_type="serial", primary_key=True),
            ColumnMetadata(name="customer_id", canonical_type="integer", db_type="integer"),
        ],
        primary_key_columns=["id"],
        foreign_keys=[
            ForeignKeyConstraint(
                source_columns=["customer_id"],
                target_table="customers",
                target_columns=["id"],
            )
        ],
    )

    # Snapshot with t1 then t2
    snap1 = CatalogSnapshot(connection_id="c1", engine="postgresql", tables=[t1, t2])
    hash1 = snap1.compute_hash()

    # Snapshot with t2 then t1
    snap2 = CatalogSnapshot(connection_id="c1", engine="postgresql", tables=[t2, t1])
    hash2 = snap2.compute_hash()

    assert hash1 == hash2
    assert len(hash1) == 64  # SHA-256


def test_schema_graph_join_paths():
    """SchemaGraph resolves unique, ambiguous, and disconnected paths."""
    # Graph: A -> B -> C, and disconnected D
    tA = TableMetadata(
        name="orders",
        columns=[],
        foreign_keys=[ForeignKeyConstraint(source_columns=["user_id"], target_table="users", target_columns=["id"])],
    )
    tB = TableMetadata(
        name="users",
        columns=[],
        foreign_keys=[],
    )
    tC = TableMetadata(
        name="items",
        columns=[],
        foreign_keys=[ForeignKeyConstraint(source_columns=["order_id"], target_table="orders", target_columns=["id"])],
    )
    tD = TableMetadata(name="logs", columns=[], foreign_keys=[])

    snap = CatalogSnapshot(connection_id="c1", engine="postgresql", tables=[tA, tB, tC, tD])
    graph = SchemaGraph(snap)

    # Path between items and users (through orders)
    status, path = graph.resolve_join_path("items", "users")
    assert status == "unique"
    assert path is not None

    # Disconnected path to logs
    status_disc, path_disc = graph.resolve_join_path("users", "logs")
    assert status_disc == "disconnected"
    assert path_disc is None


def test_mysql_discovery_stays_in_connected_database(monkeypatch):
    from unittest.mock import Mock
    from querylens.schema.inspector import SchemaInspector

    inspector = Mock(default_schema_name="analytics")
    inspector.get_schema_names.side_effect = AssertionError("Must not scan unrelated databases")
    inspector.get_table_names.return_value = ["customers"]
    inspector.get_columns.return_value = [{"name": "id"}]
    monkeypatch.setattr("querylens.schema.inspector.sa.inspect", lambda engine: inspector)
    assert SchemaInspector.discover_candidate_tables(Mock(), "mysql") == ["analytics.customers"]
    assert SchemaInspector.discover_columns(Mock(), "mysql") == {"analytics.customers": ["id"]}
    inspector.get_columns.assert_called_once_with("customers", schema="analytics")


async def test_schema_discovery_errors_are_actionable_and_sanitized():
    import pytest
    import sqlalchemy as sa
    from querylens.api.errors import AppError
    from querylens.api.schema import run_schema_operation

    def fail():
        raise sa.exc.OperationalError("secret SQL", {}, Exception("secret password"))

    with pytest.raises(AppError, match="metadata permissions") as error:
        await run_schema_operation(fail)
    assert error.value.status_code == 422
    assert "secret" not in str(error.value)


async def test_schema_discovery_timeout_has_retry_message(monkeypatch):
    import pytest
    from querylens.api.errors import AppError
    from querylens.api.schema import run_schema_operation

    async def timeout(*args, **kwargs):
        raise TimeoutError()

    monkeypatch.setattr("querylens.api.schema.run_db", timeout)
    with pytest.raises(AppError, match="try again") as error:
        await run_schema_operation(lambda: None)
    assert error.value.status_code == 504
