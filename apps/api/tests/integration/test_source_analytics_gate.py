"""Real source-driver gates. CI requires fixtures; local PostgreSQL is disposable."""

import time

import pytest



@pytest.mark.parametrize("date_column", ["day", "moment"])
def test_manual_saved_parameterized_source_journey(analytics_source_env, date_column):
    """HTTP admission, metadata probe, guarded result, audit and filtered resave."""
    env = analytics_source_env
    namespace = env.snapshot.tables[0].namespace

    def post(path, payload):
        response = env.client.post("/api/v1/" + path, json=payload, headers=env.headers)
        assert response.status_code in (201, 202), response.text
        return response.json()

    def wait_run(query_id):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = env.client.get("/api/v1/queries/" + query_id)
            assert response.status_code == 200, response.text
            run = response.json()
            if run["status"] in ("completed", "failed", "rejected"):
                assert run["status"] == "completed", str(run)
                return run
            time.sleep(0.02)
        pytest.fail("Source execution did not complete")

    # Literal placeholder text and literal double percents survive both driver
    # metadata probing and guarded execution, even with an injection-like binding.
    literal = "%(p_category_category)s :p_category_category %%"
    sql = (f"SELECT id, category, day, '{literal}' AS note FROM {namespace}.ql_analytics_gate "
           f"WHERE category = 'safe' AND {date_column} >= '2026-01-01' AND {date_column} < '2026-02-01' ORDER BY id")
    manual = wait_run(post("queries/sql", {"connection_id": env.connection_id, "sql": sql, "max_rows": 100})["query_id"])
    assert [row["id"] for row in manual["rows"]] == ["1", "2"]
    definitions = env.client.get(f'/api/v1/queries/{manual["query_id"]}/parameters').json()["definitions"]
    saved = post("saved-questions", {"source_query_id": manual["query_id"], "title": "Source gate", "parameters": definitions})
    selected = {item["name"]: item["default_value"] for item in definitions}
    selected["result_count"] = 200
    filtered = wait_run(post(f'saved-questions/{saved["id"]}/run', {"expected_revision": 1, "parameters": selected})["query_id"])
    assert [row["id"] for row in filtered["rows"]] == ["1", "2"]
    assert all(row["note"] == literal for row in filtered["rows"])
    assert filtered["context"]["resolved_parameters"]["max_rows"] == 200
    category = next(item for item in definitions if item["param_type"] == "category")
    selected[category["name"]] = "' OR SLEEP(30) -- "
    injected = wait_run(post(f'saved-questions/{saved["id"]}/run', {"expected_revision": 1, "parameters": selected})["query_id"])
    assert [row["id"] for row in injected["rows"]] == ["4"]
    assert injected["rows"][0]["note"] == literal
    rediscovered = env.client.get(f'/api/v1/queries/{injected["query_id"]}/parameters').json()["definitions"]
    resaved = post("saved-questions", {"source_query_id": injected["query_id"], "title": "Filtered resave", "parameters": rediscovered})
    rerun = wait_run(post(f'saved-questions/{resaved["id"]}/run', {"expected_revision": 1, "parameters": {}})["query_id"])
    assert [row["id"] for row in rerun["rows"]] == ["4"]
    rejected = env.client.post("/api/v1/queries/sql", headers=env.headers, json={
        "connection_id": env.connection_id, "sql": f"DELETE FROM {namespace}.ql_analytics_gate", "max_rows": 100,
    })
    assert rejected.status_code == 202, rejected.text
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        denied = env.client.get("/api/v1/queries/" + rejected.json()["query_id"]).json()
        if denied["status"] == "rejected":
            break
        time.sleep(0.02)
    assert denied["status"] == "rejected", denied
    with env.source_engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM ql_analytics_gate").scalar_one() == 4
