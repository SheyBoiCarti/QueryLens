"""Connection setup imports schema atomically while preserving explicit policies."""

import pytest
import sqlalchemy as sa

from querylens.api.errors import AppError
from querylens.connections.models import ConnectionCreate
from querylens.connections.service import ConnectionService
from querylens.persistence.tables import connections
from querylens.schema.snapshots import get_latest_snapshot


@pytest.fixture
def source(monkeypatch):
    from querylens.connections import service

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE customers (id INTEGER PRIMARY KEY, name TEXT)")
    monkeypatch.setattr(service, "dispatch_test_connection", lambda **kwargs: (True, "PostgreSQL 17", "OK"))
    monkeypatch.setattr(service.get_registry(), "get_or_create", lambda **kwargs: engine)
    yield engine
    engine.dispose()


def payload(**overrides):
    return ConnectionCreate(**dict(
        name="Imported", engine="postgresql", host="db.example.test", port=5432,
        database="analytics", username="reader", password="secret", import_schema=True,
    ), **overrides)


def test_import_saves_discovered_policy_and_snapshot(analytics_env, source):
    saved = ConnectionService().create(analytics_env.owner_id, payload())
    assert saved.allowed_tables == {"main.customers": ["id", "name"]}
    snapshot = get_latest_snapshot(saved.id)
    assert snapshot is not None
    assert snapshot.policy_version == 1
    assert [table.name for table in snapshot.tables] == ["customers"]
    assert [column.name for column in snapshot.tables[0].columns] == ["id", "name"]


@pytest.mark.parametrize("policy", [{}, {"main.customers": ["id"]}])
def test_import_preserves_explicit_policy(analytics_env, source, policy):
    saved = ConnectionService().create(analytics_env.owner_id, payload(allowed_tables=policy))
    assert saved.allowed_tables == policy
    snapshot = get_latest_snapshot(saved.id)
    assert snapshot is not None
    if not policy:
        assert snapshot.tables == []
    else:
        assert [column.name for column in snapshot.tables[0].columns] == ["id"]


def test_failed_verification_does_not_save_connection(analytics_env, monkeypatch):
    from querylens.connections import service

    monkeypatch.setattr(service, "dispatch_test_connection", lambda **kwargs: (False, "", "Access denied"))
    with pytest.raises(AppError, match="Access denied"):
        ConnectionService().create(analytics_env.owner_id, payload())
    with analytics_env.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(connections).where(connections.c.name == "Imported")) == 0


def test_failed_discovery_does_not_save_connection_or_leak_details(analytics_env, source, monkeypatch):
    from querylens.schema.inspector import SchemaInspector

    def fail(*args):
        raise sa.exc.OperationalError("secret SQL", {}, Exception("secret password"))

    monkeypatch.setattr(SchemaInspector, "discover_columns", fail)
    with pytest.raises(AppError, match="could not import the schema") as error:
        ConnectionService().create(analytics_env.owner_id, payload())
    assert "secret" not in str(error.value)
    with analytics_env.engine.connect() as conn:
        assert conn.scalar(sa.select(sa.func.count()).select_from(connections).where(connections.c.name == "Imported")) == 0
