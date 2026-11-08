import datetime as dt
import time


from querylens.persistence.tables import query_runs


def test_completed_get_maps_context_origin_expiry_and_eviction(analytics_env, completed_run):
    env = analytics_env
    run = completed_run(origin="manual_sql", rows=[{"id": "123"}])
    response = env.client.get("/api/v1/queries/" + run["id"])
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["origin"] == "manual_sql"
    assert data["context"]["canonical_sql_template"] == "SELECT id FROM public.customers"
    assert data["presentation"]["value"] == "123"
    expiry = dt.datetime.fromisoformat(data["results_expires_at"])
    assert 0 < (expiry - dt.datetime.now(dt.UTC)).total_seconds() <= 300
    env.cache.evict(run["id"])
    expired = env.client.get("/api/v1/queries/" + run["id"]).json()
    assert not expired["results_available"]
    assert all(key not in expired for key in ("rows", "presentation", "results_expires_at"))
    assert expired["context"]
    assert env.client.get("/api/v1/queries/" + run["id"] + "/export").status_code == 410


def test_owner_and_history_relationship_mapping(analytics_env, completed_run):
    env = analytics_env
    parent = completed_run()
    child = completed_run(
        origin="follow_up",
        parent_query_id=parent["id"],
        source_query_id=parent["id"],
        saved_question_id="retained-definition",
        saved_question_version=2,
    )
    items = env.client.get("/api/v1/queries/history").json()["items"]
    item = next(item for item in items if item["id"] == child["id"])
    assert item["origin"] == "follow_up" and item["parent_query_id"] == parent["id"]
    assert item["source_query_id"] == parent["id"] and item["saved_question_version"] == 2
    with env.engine.begin() as conn:
        conn.execute(query_runs.update().where(query_runs.c.id == child["id"]).values(user_id=env.foreign_id))
    assert env.client.get("/api/v1/queries/" + child["id"]).status_code == 404


def test_expired_entry_does_not_extend_lifetime(analytics_env, completed_run):
    env = analytics_env
    run = completed_run()
    entry = env.cache.get_entry(run["id"])
    assert entry is not None
    assert env.cache.get_entry(run["id"]).expires_at == entry.expires_at

    from dataclasses import replace

    env.cache._cache[run["id"]] = replace(entry, expires_at=time.monotonic() - 1)
    data = env.client.get("/api/v1/queries/" + run["id"]).json()
    assert not data["results_available"] and "presentation" not in data


def test_hidden_historical_labels_metrics_and_policy_invalidation(analytics_env, completed_run):
    from querylens.domain.analytics import LabelReference, MetricReference, RunContext
    from querylens.persistence.tables import connections
    from querylens.schema.snapshots import save_snapshot

    env = analytics_env
    run = completed_run()
    context = RunContext.model_validate_json(run["run_context_json"])
    hidden = LabelReference(
        namespace="private", table_name="secret", column_name="value", display_name="Confidential", version=1
    )
    visible = LabelReference(
        namespace="public", table_name="customers", column_name="id", display_name="Customer number", version=1
    )
    context = context.model_copy(
        update={
            "label_references": (hidden, visible),
            "metric_references": (MetricReference(id="removed", key="secret_metric", version=1, dsl_hash="a" * 64),),
        }
    )
    with env.engine.begin() as conn:
        conn.execute(
            query_runs.update().where(query_runs.c.id == run["id"]).values(run_context_json=context.model_dump_json())
        )
    data = env.client.get("/api/v1/queries/" + run["id"]).json()
    assert [label["display_name"] for label in data["context"]["label_references"]] == ["Customer number"]
    assert data["context"]["metric_references"] == []
    assert data["presentation"]["verified_definitions"] == []
    # Install the current policy snapshot, without needing any source credentials.
    with env.engine.begin() as conn:
        conn.execute(connections.update().where(connections.c.id == env.connection_id).values(policy_version=2))
    snapshot = env.snapshot.model_copy(deep=True)
    snapshot.policy_version = 2
    snapshot.snapshot_hash = snapshot.compute_hash()
    save_snapshot(snapshot)
    data = env.client.get("/api/v1/queries/" + run["id"]).json()
    assert not data["results_available"]
    assert all(key not in data for key in ("rows", "presentation", "results_expires_at"))
    assert not env.client.get("/api/v1/queries/history").json()["items"][0]["results_available"]
    assert env.client.get("/api/v1/queries/" + run["id"] + "/export").status_code == 410


def test_policy_revocation_with_stale_snapshot_never_reflects_source(analytics_env, completed_run, monkeypatch):
    from querylens.persistence.tables import connections
    from querylens.schema.catalog import CatalogService

    env = analytics_env
    run = completed_run()

    def forbidden(*args, **kwargs):
        pytest.fail("Result delivery attempted source reflection")

    import pytest

    monkeypatch.setattr(CatalogService, "refresh_catalog", forbidden)
    with env.engine.begin() as conn:
        conn.execute(connections.update().where(connections.c.id == env.connection_id).values(policy_version=2))
    data = env.client.get("/api/v1/queries/" + run["id"])
    assert data.status_code == 200, data.text
    assert not data.json()["results_available"]
    assert "presentation" not in data.json()
    assert env.client.get("/api/v1/queries/" + run["id"] + "/export").status_code == 410
