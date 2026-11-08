"""Exercise explicit migrations on a disposable PostgreSQL metadata database."""

import datetime as dt
import json
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from querylens.persistence.repositories.query_runs import QueryRunRepository
from querylens.persistence.repositories.history import HistoryRepository
from querylens.persistence.retention import run_retention_cleanup
from querylens.persistence.tables import (
    catalog_labels,
    connections,
    metadata,
    query_attempts,
    query_runs,
    saved_questions,
    users,
)
from querylens.domain.analytics import RunContext


def migration_config():
    api_root = Path(__file__).resolve().parents[2]
    cfg = Config(str(api_root / "alembic.ini"))
    cfg.set_main_option("script_location", str(api_root / "migrations"))
    return cfg


def test_postgres_upgrade_legacy_downgrade_reupgrade(analytics_postgres_url):
    from querylens.config import Settings, set_settings

    set_settings(Settings(_env_file=None, environment="test", metadata_database_url=analytics_postgres_url))
    cfg = migration_config()
    command.upgrade(cfg, "0002_review_hardening")
    engine = sa.create_engine(analytics_postgres_url)
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("INSERT INTO users(id,email,password_hash) VALUES ('old-user','old@test','hash')"))
            conn.execute(
                sa.text("""INSERT INTO connections(id,user_id,name,engine,host,port,database,username,encrypted_password)
                VALUES ('old-conn','old-user','Old','postgresql','fixture',5432,'fixture','reader','unused')""")
            )
            conn.execute(
                sa.text("""INSERT INTO query_runs(id,user_id,connection_id,question,status,canonical_sql)
                VALUES ('old-run','old-user','old-conn','Old question','completed','SELECT 1 LIMIT 101')""")
            )
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            row = conn.execute(sa.text("SELECT * FROM query_runs WHERE id='old-run'")).mappings().one()
            assert row["origin"] == "natural_language" and row["run_context_json"] is None
            assert row["snapshot_hash"] is None and row["policy_version"] is None and row["semantic_version"] is None
            assert row["canonical_sql"] == "SELECT 1 LIMIT 101"
            assert conn.execute(sa.text("SELECT semantic_version FROM connections")).scalar_one() == 1
            assert (
                compare_metadata(MigrationContext.configure(conn, opts={"compare_server_default": True}), metadata)
                == []
            )
        inspector = sa.inspect(engine)
        fks = {fk["name"]: fk for fk in inspector.get_foreign_keys("query_runs")}
        for name in ("fk_query_runs_parent", "fk_query_runs_source"):
            assert fks[name]["options"]["ondelete"] == "SET NULL"
        assert any(c["name"] == "chk_query_runs_origin" for c in inspector.get_check_constraints("query_runs"))
        indexes = {i["name"]: i for i in inspector.get_indexes("catalog_labels")}
        assert indexes["uq_catalog_labels_table"]["unique"]
        assert "column_name IS NULL" in indexes["uq_catalog_labels_table"]["dialect_options"]["postgresql_where"]
        assert "column_name IS NOT NULL" in indexes["uq_catalog_labels_column"]["dialect_options"]["postgresql_where"]
        command.downgrade(cfg, "0002_review_hardening")
        assert "saved_questions" not in sa.inspect(engine).get_table_names()
        assert "origin" not in {c["name"] for c in sa.inspect(engine).get_columns("query_runs")}
        command.upgrade(cfg, "head")
        with engine.begin() as conn:
            assert (
                compare_metadata(MigrationContext.configure(conn, opts={"compare_server_default": True}), metadata)
                == []
            )
            assert (
                conn.execute(sa.text("SELECT question FROM query_runs WHERE id='old-run'")).scalar_one()
                == "Old question"
            )
    finally:
        engine.dispose()
        command.downgrade(cfg, "base")


# Both dialects must implement partial uniqueness and deletion semantics.
@pytest.fixture(params=["sqlite", "postgresql"])
def analytics_schema_engine(request):
    if request.param == "postgresql":
        url = request.getfixturevalue("analytics_postgres_url")
        from querylens.config import Settings, set_settings

        set_settings(Settings(_env_file=None, environment="test", metadata_database_url=url))
        command.upgrade(migration_config(), "head")
        engine = sa.create_engine(url)
    else:
        engine = sa.create_engine("sqlite://")

        @sa.event.listens_for(engine, "connect")
        def enable_fks(dbapi, _):
            dbapi.execute("PRAGMA foreign_keys=ON")

        metadata.create_all(engine)
    try:
        with engine.begin() as conn:
            conn.execute(users.insert().values(id="owner", email="owner@example.test", password_hash="hash"))
            conn.execute(
                connections.insert().values(
                    id="source",
                    user_id="owner",
                    name="Fixture",
                    engine="mysql",
                    host="fixture.invalid",
                    port=3306,
                    database="analytics_db",
                    username="reader",
                    encrypted_password="unused",
                )
            )
        yield engine
    finally:
        engine.dispose()


def test_label_uniqueness_uses_physical_namespace_and_target(analytics_schema_engine):
    engine = analytics_schema_engine
    base = dict(connection_id="source", namespace="analytics_db", table_name="customers", display_name="Customers")
    with engine.begin() as conn:
        conn.execute(catalog_labels.insert().values(id="table", **base))
        conn.execute(catalog_labels.insert().values(id="column", column_name="id", **base))
        conn.execute(catalog_labels.insert().values(id="other-column", column_name="name", **base))
        conn.execute(catalog_labels.insert().values(id="other-db", **{**base, "namespace": "other_db"}))
    for values in ({"id": "duplicate-table"}, {"id": "duplicate-column", "column_name": "id"}):
        with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
            conn.execute(catalog_labels.insert().values(**base, **values))
    with pytest.raises(sa.exc.IntegrityError), engine.begin() as conn:
        # MySQL namespaces are mandatory physical database names, never public.
        conn.execute(
            catalog_labels.insert().values(id="missing-db", connection_id="source", table_name="t", display_name="T")
        )


def seed_definition(conn):
    conn.execute(
        saved_questions.insert().values(
            id="saved",
            user_id="owner",
            connection_id="source",
            title="Independent definition",
            canonical_sql_template="SELECT id FROM analytics_db.customers",
            effective_question="List IDs",
            parameter_defaults_json='{"country":"South Africa"}',
            snapshot_hash="a" * 64,
            policy_version=1,
            semantic_version=1,
        )
    )


def seed_parent_child(conn):
    repo = QueryRunRepository(conn)
    repo.create("parent", "owner", "source", "List IDs")
    repo.create(
        "child",
        "owner",
        "source",
        "Only South Africa",
        origin="saved_question",
        parent_query_id="parent",
        source_query_id="parent",
        saved_question_id="saved",
        saved_question_version=2,
        saved_definition_json='{"revision":2,"values":{"country":"South Africa"}}',
    )
    ctx = RunContext(
        effective_question="List customer IDs in South Africa",
        canonical_sql_template="SELECT id FROM analytics_db.customers WHERE country = 'South Africa'",
        snapshot_hash="a" * 64,
        policy_version=1,
        semantic_version=1,
    )
    assert repo.complete("child", ctx, ctx.canonical_sql_template + " LIMIT 101", [], [], False)
    repo.record_attempt("attempt", "parent", 1, "completed")
    return repo.get("child")


def test_definition_and_parent_deletion_preserve_child_audit(analytics_schema_engine):
    engine = analytics_schema_engine
    with engine.begin() as conn:
        seed_definition(conn)
        before = seed_parent_child(conn)
        conn.execute(saved_questions.delete().where(saved_questions.c.id == "saved"))
        assert QueryRunRepository(conn).get("child")["saved_question_id"] == "saved"
        assert not HistoryRepository(conn).delete_run("parent", "foreign")
        assert HistoryRepository(conn).delete_run("parent", "owner")
        child = QueryRunRepository(conn).get("child")
        for key in ("run_context_json", "saved_definition_json", "saved_question_id", "saved_question_version"):
            assert child[key] == before[key]
        assert child["parent_query_id"] is None and child["source_query_id"] is None
        assert conn.execute(sa.select(sa.func.count()).select_from(query_attempts)).scalar_one() == 0


def test_retention_removes_run_context_independently_of_definitions(analytics_schema_engine):
    engine = analytics_schema_engine
    with engine.begin() as conn:
        seed_definition(conn)
        before = seed_parent_child(conn)
        conn.execute(
            query_runs.update()
            .where(query_runs.c.id == "parent")
            .values(created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10))
        )
        assert run_retention_cleanup(conn=conn)["deleted_query_runs"] == 1
        child = QueryRunRepository(conn).get("child")
        assert child["parent_query_id"] is None and child["source_query_id"] is None
        assert child["run_context_json"] == before["run_context_json"]
        conn.execute(
            query_runs.update()
            .where(query_runs.c.id == "child")
            .values(created_at=dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=10))
        )
        assert run_retention_cleanup(conn=conn)["deleted_query_runs"] == 1
        assert conn.execute(sa.select(sa.func.count()).select_from(query_runs)).scalar_one() == 0
        definition = conn.execute(sa.select(saved_questions)).mappings().one()
        assert definition["revision"] == 1 and definition["default_max_rows"] == 100
        assert definition["author_limit"] is None
        assert json.loads(definition["parameter_defaults_json"]) == {"country": "South Africa"}


def test_connection_cascade_removes_definitions_labels_and_runs(analytics_schema_engine):
    with analytics_schema_engine.begin() as conn:
        seed_definition(conn)
        seed_parent_child(conn)
        conn.execute(
            catalog_labels.insert().values(
                id="label",
                connection_id="source",
                namespace="analytics_db",
                table_name="customers",
                display_name="Customers",
            )
        )
        conn.execute(connections.delete().where(connections.c.id == "source"))
        for table in (saved_questions, catalog_labels, query_runs, query_attempts):
            assert conn.execute(sa.select(sa.func.count()).select_from(table)).scalar_one() == 0


def test_database_rejects_unknown_origins(analytics_schema_engine):
    with pytest.raises(sa.exc.IntegrityError), analytics_schema_engine.begin() as conn:
        conn.execute(
            query_runs.insert().values(
                id="invalid",
                user_id="owner",
                connection_id="source",
                question="Invalid",
                origin="unknown",
            )
        )
