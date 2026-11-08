"""Global pytest fixtures and path configuration."""

import sys
from pathlib import Path

# Add repo root to sys.path so datasets and benchmarks can be imported
repo_root = Path(__file__).resolve().parents[3]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

import json
import shutil
import subprocess
import tempfile
import uuid
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient


@pytest.fixture
def analytics_env(monkeypatch):
    """Real owner cookies/CSRF, FK-enforced metadata, and isolated singletons.

    No auth bypasses or provider/executor spies: tests install spies explicitly.
    """
    from querylens import config
    from querylens.auth import service
    from querylens.auth.crypto import hash_password
    from querylens.connections import keyring, registry
    from querylens.jobs import admission, results
    from querylens.llm import fake, live
    from querylens.persistence import session
    from querylens.persistence.tables import connections, metadata
    from querylens.schema.snapshots import save_snapshot
    from querylens.domain.schema import CatalogSnapshot, TableMetadata, ColumnMetadata
    from querylens.utils import workers

    engine = sa.create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=sa.pool.StaticPool)

    @sa.event.listens_for(engine, "connect")
    def enable_fks(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    metadata.create_all(engine)
    settings = config.Settings(_env_file=None, environment="test", llm_provider="fake",
                               metadata_database_url="sqlite://", development_auth_bypass=False)
    for module, attr, value in (
        (config, "_global_settings", settings), (session, "_engine", engine),
        (results, "_global_result_cache", results.ResultCache()),
        (admission, "_controller_singleton", None), (fake, "_fake_provider_singleton", None),
        (live, "_live_provider_singleton", None), (workers, "_db_executor", None),
        (service, "_rate_limit_map", {}), (keyring, "_keyring", dict(keyring._keyring)),
        (keyring, "_active_key_id", keyring._active_key_id), (registry, "_registry", None),
    ):
        monkeypatch.setattr(module, attr, value)
    from querylens.main import create_app
    app = create_app(settings)
    auth = service.AuthService()
    password = "Analytics-test-password-123!"
    owner = auth.create_user("analytics-owner@example.test", hash_password(password))
    foreign = auth.create_user("analytics-foreign@example.test", hash_password(password))
    snapshots = []
    for user in (owner, foreign):
        connection_id = str(uuid.uuid4())
        with engine.begin() as conn:
            conn.execute(connections.insert().values(
                id=connection_id, user_id=user["id"], name="Fixture", engine="postgresql", host="fixture.invalid",
                port=5432, database="fixture", username="reader", encrypted_password="never-used",
                allowed_tables=json.dumps({"public.customers": ["id", "country"]}),
            ))
        snapshot = CatalogSnapshot(connection_id=connection_id, engine="postgresql", tables=[
            TableMetadata(namespace="public", name="customers", columns=[
                ColumnMetadata(name="id", canonical_type="integer", db_type="integer"),
                ColumnMetadata(name="country", canonical_type="string", db_type="text"),
            ]),
        ])
        snapshot.snapshot_hash = snapshot.compute_hash()
        save_snapshot(snapshot)
        snapshots.append(snapshot)

    try:
        with TestClient(app, base_url="https://testserver") as client:
            response = client.post("/api/v1/auth/login", json={"email": owner["email"], "password": password},
                                   headers={"Origin": settings.allowed_origins[0], "X-QueryLens-Client": "web"})
            assert response.status_code == 200, response.text
            headers = {"Origin": settings.allowed_origins[0], "X-CSRF-Token": response.json()["csrf_token"]}
            yield SimpleNamespace(client=client, app=app, engine=engine, owner_id=owner["id"],
                                  foreign_id=foreign["id"], connection_id=snapshots[0].connection_id,
                                  foreign_connection_id=snapshots[1].connection_id, snapshot=snapshots[0],
                                  foreign_snapshot=snapshots[1], headers=headers, password=password,
                                  cache=results.get_result_cache())
    finally:
        workers.shutdown_db_executor()
        engine.dispose()


@pytest.fixture
def completed_run(analytics_env):
    """Validated completed metadata/cache without source I/O."""
    from querylens.domain.analytics import RunContext, ObjectReference
    from querylens.persistence.repositories.query_runs import QueryRunRepository
    from querylens.sql.policy import validate_and_bound_sql

    def create(*, query_id=None, sql="SELECT id FROM public.customers", rows=None, **create_options):
        env = analytics_env
        query_id = query_id or str(uuid.uuid4())
        token = validate_and_bound_sql(sql, env.connection_id, "postgresql", env.snapshot, max_rows=100)
        repo = QueryRunRepository()
        repo.create(query_id, env.owner_id, env.connection_id, "List customer IDs", **create_options)
        context = RunContext(
            effective_question="List customer IDs", canonical_sql_template=sql,
            snapshot_hash=env.snapshot.snapshot_hash, policy_version=1, semantic_version=1,
            referenced_objects=(ObjectReference(namespace="public", table_name="customers", column_name="id",
                                                 canonical_type="integer", db_type="integer"),),
        )
        assert repo.complete(query_id, context, token.canonical_sql, [], [], False)
        env.cache.put(query_id, env.snapshot.snapshot_hash,
                      [{"name": "id", "type": "integer", "db_type": "integer"}],
                      [{"id": 1}] if rows is None else rows, connection_id=env.connection_id)
        return repo.get(query_id, env.owner_id)

    return create


@pytest.fixture
def analytics_postgres_url(monkeypatch):
    """New local cluster; never use application database credentials."""
    from querylens import config
    monkeypatch.setattr(config, "_global_settings", None)
    initdb = shutil.which("initdb")
    if not initdb:
        candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin/initdb"), reverse=True)
        initdb = str(candidates[0]) if candidates else None
    if not initdb:
        pytest.fail("PostgreSQL server binaries are required for the analytics migration gate")
    pg_ctl = str(Path(initdb).with_name("pg_ctl"))
    with tempfile.TemporaryDirectory(prefix="ql-pg-") as root:
        data = str(Path(root) / "data")
        log = str(Path(root) / "postgres.log")
        subprocess.run([initdb, "-D", data, "-A", "trust", "-U", "postgres", "--no-locale", "--encoding=UTF8"],
                       check=True, capture_output=True, text=True)
        subprocess.run([pg_ctl, "-D", data, "-l", log, "-o", f"-F -h '' -k {root}", "-w", "start"],
                       check=True, capture_output=True, text=True)
        try:
            yield f"postgresql+psycopg://postgres@/postgres?host={root}"
        finally:
            subprocess.run([pg_ctl, "-D", data, "-m", "immediate", "-w", "stop"],
                           check=True, capture_output=True, text=True)
