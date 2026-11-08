"""Authenticated saved question journeys, parameter discovery, and direct execution (Contract C09)."""

import time
import pytest

from querylens.domain.query import QueryResult
from querylens.execution.executor import SafeExecutor


def wait_terminal(env, query_id):
    for _ in range(200):
        run = env.client.get(f"/api/v1/queries/{query_id}")
        assert run.status_code == 200, run.text
        if run.json()["status"] in {"completed", "failed", "rejected", "cancelled", "interrupted"}:
            return run.json()
        time.sleep(0.01)
    pytest.fail("Query run did not become terminal in time")


def test_parameter_discovery_endpoint(analytics_env, completed_run):
    env = analytics_env
    run = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    # 1. Parameter discovery requires owner completed run
    res = env.client.get(f"/api/v1/queries/{run['id']}/parameters")
    assert res.status_code == 200, res.text
    data = res.json()
    assert "template_fingerprint" in data
    assert "definitions" in data
    def_names = [d["name"] for d in data["definitions"]]
    assert "country" in def_names
    assert "result_count" in def_names

    # Result count default uses run's max_rows (100), not sentinel (101)
    rc_def = next(d for d in data["definitions"] if d["name"] == "result_count")
    assert rc_def["default_value"] == 100

    # Foreign query returns 404
    login_foreign = env.client.post(
        "/api/v1/auth/login",
        json={"email": "analytics-foreign@example.test", "password": env.password},
        headers={"Origin": "http://localhost:5173", "X-QueryLens-Client": "web"},
    )
    foreign_headers = {"Origin": "http://localhost:5173", "X-CSRF-Token": login_foreign.json()["csrf_token"]}
    res_foreign = env.client.get(f"/api/v1/queries/{run['id']}/parameters", headers=foreign_headers)
    assert res_foreign.status_code == 404


def test_saved_question_crud_lifecycle(analytics_env, completed_run):
    env = analytics_env
    run = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    # Discover slots
    disc = env.client.get(f"/api/v1/queries/{run['id']}/parameters").json()
    country_def = next(d for d in disc["definitions"] if d["name"] == "country")

    # 1. Create saved question
    payload = {
        "source_query_id": run["id"],
        "title": "Customers by Country",
        "description": "Filter customers by country code",
        "parameters": [
            {
                "slot_id": country_def["slot_id"],
                "name": country_def["name"],
                "label": "Country Code",
                "param_type": "category",
                "source_type": "string",
                "target": country_def["target"],
                "default_value": "USA",
                "allowed_values": ["USA", "CAN", "MEX"],
            }
        ],
        "chart_preference": "table",
    }
    create_res = env.client.post("/api/v1/saved-questions", headers=env.headers, json=payload)
    assert create_res.status_code == 201, create_res.text
    saved = create_res.json()
    assert saved["title"] == "Customers by Country"
    assert saved["revision"] == 1
    assert saved["connection_id"] == env.connection_id
    saved_id = saved["id"]

    # 2. Get saved question detail
    get_res = env.client.get(f"/api/v1/saved-questions/{saved_id}")
    assert get_res.status_code == 200
    assert get_res.json()["title"] == "Customers by Country"

    # 3. List and search saved questions
    list_res = env.client.get(f"/api/v1/saved-questions?connection_id={env.connection_id}&search=Customers")
    assert list_res.status_code == 200
    items = list_res.json()["items"]
    assert len(items) >= 1
    assert any(i["id"] == saved_id for i in items)

    # 4. Patch revision optimistic concurrency
    patch_res = env.client.patch(
        f"/api/v1/saved-questions/{saved_id}",
        headers=env.headers,
        json={"expected_revision": 1, "title": "Updated Customer Title"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["revision"] == 2
    assert patch_res.json()["title"] == "Updated Customer Title"

    # Stale revision returns 409
    patch_stale = env.client.patch(
        f"/api/v1/saved-questions/{saved_id}",
        headers=env.headers,
        json={"expected_revision": 1, "title": "Conflict Title"},
    )
    assert patch_stale.status_code == 409

    # 5. Duplicate
    dup_res = env.client.post(
        f"/api/v1/saved-questions/{saved_id}/duplicate",
        headers=env.headers,
        json={"title": "Duplicated Customer Query"},
    )
    assert dup_res.status_code == 201
    dup_data = dup_res.json()
    assert dup_data["id"] != saved_id
    assert dup_data["revision"] == 1
    assert dup_data["title"] == "Duplicated Customer Query"

    # 6. Delete
    del_res = env.client.delete(f"/api/v1/saved-questions/{saved_id}", headers=env.headers)
    assert del_res.status_code == 204

    # Now 404
    assert env.client.get(f"/api/v1/saved-questions/{saved_id}").status_code == 404


def test_saved_question_direct_rerun_execution(analytics_env, completed_run, monkeypatch):
    env = analytics_env
    run = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    disc = env.client.get(f"/api/v1/queries/{run['id']}/parameters").json()
    country_def = next(d for d in disc["definitions"] if d["name"] == "country")

    payload = {
        "source_query_id": run["id"],
        "title": "Customers Rerun Test",
        "parameters": [
            {
                "slot_id": country_def["slot_id"],
                "name": country_def["name"],
                "label": "Country Code",
                "param_type": "category",
                "source_type": "string",
                "target": country_def["target"],
                "default_value": "USA",
                "allowed_values": ["USA", "CAN"],
            }
        ],
    }
    create_res = env.client.post("/api/v1/saved-questions", headers=env.headers, json=payload)
    assert create_res.status_code == 201
    saved_id = create_res.json()["id"]

    calls = []

    def execute(token, **kwargs):
        calls.append(token)
        return QueryResult([{"name": "id", "type": "integer", "db_type": "integer"}], [{"id": 42}], 1, False, 1)

    monkeypatch.setattr(SafeExecutor, "execute", execute)
    import querylens.pipeline.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "get_fake_llm_provider", lambda: pytest.fail("direct path used provider"))

    # Run saved question with changed filter value "CAN"
    run_res = env.client.post(
        f"/api/v1/saved-questions/{saved_id}/run",
        headers=env.headers,
        json={"parameters": {"country": "CAN"}, "expected_revision": 1},
    )
    assert run_res.status_code == 202, run_res.text
    query_id = run_res.json()["query_id"]

    completed = wait_terminal(env, query_id)
    assert completed["status"] == "completed", completed
    assert completed["origin"] == "saved_question"
    assert completed["saved_question_id"] == saved_id
    assert completed["saved_question_version"] == 1
    assert completed["rows"] == [{"id": 42}]

    # Assert executed token used DBAPI parameter binding for CAN
    assert len(calls) == 1
    executed_token = calls[0]
    binding = next(b for b in executed_token.bindings if b.value == "CAN")
    assert binding.name.startswith("p_")
    assert "CAN" not in executed_token.canonical_sql


def test_saved_question_review_required_on_catalog_drift(analytics_env, completed_run):
    """When referenced table/column in saved definition is missing or modified, return 409 SAVED_QUESTION_REVIEW_REQUIRED."""
    env = analytics_env
    run = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    disc = env.client.get(f"/api/v1/queries/{run['id']}/parameters").json()
    country_def = next(d for d in disc["definitions"] if d["name"] == "country")

    payload = {
        "source_query_id": run["id"],
        "title": "Drift Test Question",
        "parameters": [country_def],
    }
    create_res = env.client.post("/api/v1/saved-questions", headers=env.headers, json=payload)
    assert create_res.status_code == 201
    saved_id = create_res.json()["id"]

    # Now simulate catalog drift: replace snapshot with one lacking 'country' column
    from querylens.domain.schema import CatalogSnapshot, TableMetadata, ColumnMetadata
    from querylens.schema.snapshots import save_snapshot

    drifted_snapshot = CatalogSnapshot(
        connection_id=env.connection_id,
        engine="postgresql",
        tables=[
            TableMetadata(
                namespace="public",
                name="customers",
                columns=[ColumnMetadata(name="id", canonical_type="integer", db_type="integer")],
            )
        ],
    )
    drifted_snapshot.snapshot_hash = drifted_snapshot.compute_hash()
    save_snapshot(drifted_snapshot)

    # Rerun must be rejected with 409 SAVED_QUESTION_REVIEW_REQUIRED
    rerun_res = env.client.post(
        f"/api/v1/saved-questions/{saved_id}/run",
        headers=env.headers,
        json={"parameters": {"country": "USA"}},
    )
    assert rerun_res.status_code == 409
    data = rerun_res.json()
    assert data.get("detail", {}).get("error_code") == "SAVED_QUESTION_REVIEW_REQUIRED" or "REVIEW_REQUIRED" in str(data)
