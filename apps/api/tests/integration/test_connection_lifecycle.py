"""Regression coverage for deleted connections and concurrent schema readers."""

from concurrent.futures import ThreadPoolExecutor
import threading

import sqlalchemy as sa

from querylens.persistence.session import get_engine
from querylens.persistence.tables import connections, metadata, query_runs, users


def test_sqlite_connection_deletion_cascades_to_history(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'metadata.db'}")
    try:
        metadata.create_all(engine)
        with engine.begin() as conn:
            conn.execute(users.insert().values(id="owner", email="owner@test", password_hash="unused"))
            conn.execute(connections.insert().values(
                id="source", user_id="owner", name="Source", engine="postgresql", host="unused",
                port=5432, database="unused", username="unused", encrypted_password="unused",
            ))
            conn.execute(query_runs.insert().values(
                id="run", user_id="owner", connection_id="source", question="Count customers",
            ))
        # Verify a pooled connection also retains FK enforcement.
        with engine.begin() as conn:
            conn.execute(connections.delete().where(connections.c.id == "source"))
            assert conn.execute(sa.select(query_runs.c.id)).all() == []
    finally:
        engine.dispose()


def test_history_tolerates_legacy_orphans_and_filters_inaccessible_sources(analytics_env, completed_run):
    env = analytics_env
    deleted = completed_run()
    inaccessible = completed_run()
    # Simulate records left by older SQLite builds with FK enforcement off.
    legacy_engine = sa.create_engine(env.engine.url)
    try:
        with legacy_engine.begin() as conn:
            conn.execute(query_runs.update().where(query_runs.c.id == deleted["id"])
                         .values(connection_id="deleted-source"))
            conn.execute(query_runs.update().where(query_runs.c.id == inaccessible["id"])
                         .values(connection_id=env.foreign_connection_id))
        valid = completed_run()
        response = env.client.get("/api/v1/queries/history?limit=1")
        assert response.status_code == 200, response.text
        assert [item["id"] for item in response.json()["items"]] == [valid["id"]]
        assert response.json()["next_cursor"] is None
    finally:
        legacy_engine.dispose()


def test_concurrent_cold_catalog_reads_share_one_reflection(analytics_env, monkeypatch):
    from querylens.schema.catalog import CatalogService
    from querylens.schema.snapshots import save_snapshot
    from querylens.persistence.tables import schema_snapshots

    env = analytics_env
    with env.engine.begin() as conn:
        conn.execute(schema_snapshots.delete().where(schema_snapshots.c.connection_id == env.connection_id))
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def reflect(self, user_id, connection_id):
        calls.append(connection_id)
        entered.set()
        assert release.wait(timeout=5)
        save_snapshot(env.snapshot)
        return env.snapshot

    monkeypatch.setattr(CatalogService, "_refresh_catalog", reflect)
    with ThreadPoolExecutor(max_workers=4) as executor:
        pending = [executor.submit(CatalogService().get_catalog, env.owner_id, env.connection_id) for _ in range(4)]
        assert entered.wait(timeout=5)
        release.set()
        snapshots = [future.result(timeout=5) for future in pending]
    assert calls == [env.connection_id]
    assert all(snapshot.snapshot_hash == env.snapshot.snapshot_hash for snapshot in snapshots)
