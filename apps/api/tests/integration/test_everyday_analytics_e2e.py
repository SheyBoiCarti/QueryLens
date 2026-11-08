"""End-to-end integration acceptance tests for Everyday Analytics (Task 13).

Verifies complete user journeys across:
1. Natural language query -> answer presentation & bounded execution.
2. Manual SQL editing -> bounded direct execution with origin 'manual_sql' and zero LLM calls.
3. Saved question persistence -> slot discovery -> typed rerun with origin 'saved_question' and zero LLM calls.
4. Follow-up query branching -> lineage tracking with origin 'follow_up' and parent_query_id.
5. Context drift safety -> 409 rejection when catalog snapshot changes.
"""

import time
import pytest

from querylens.domain.query import QueryResult
from querylens.execution.executor import SafeExecutor
from querylens.schema.snapshots import save_snapshot
from querylens.llm.protocol import GeneratedCandidate, LLMUsage
import querylens.pipeline.orchestrator as orchestrator


def wait_terminal(env, query_id, timeout_sec=5.0):
    start = time.time()
    while time.time() - start < timeout_sec:
        res = env.client.get(f"/api/v1/queries/{query_id}")
        assert res.status_code == 200, res.text
        data = res.json()
        if data["status"] in {"completed", "failed", "rejected", "cancelled", "interrupted"}:
            return data
        time.sleep(0.02)
    pytest.fail(f"Query {query_id} did not reach terminal state within {timeout_sec}s")


class SpyLLMProvider:
    def __init__(self, sql):
        self.sql = sql
        self.calls = 0

    async def generate(self, question, dialect, schema_context, timeout_sec=15.0):
        self.calls += 1
        return GeneratedCandidate(
            sql=self.sql,
            assumptions=["Test assumption"],
            usage=LLMUsage(prompt_tokens=10, completion_tokens=10),
        )


def test_everyday_analytics_nl_query_journey(analytics_env, monkeypatch):
    """Journey 1: Natural-language query generates bounded SQL, executes, and returns presentation."""
    env = analytics_env
    spy_llm = SpyLLMProvider("SELECT id, country FROM public.customers WHERE country = 'USA' LIMIT 101;")
    exec_calls = []

    def mock_execute(token, **kwargs):
        exec_calls.append(token)
        return QueryResult(
            columns=[
                {"name": "id", "type": "integer", "db_type": "integer"},
                {"name": "country", "type": "string", "db_type": "text"},
            ],
            rows=[{"id": 1, "country": "USA"}, {"id": 2, "country": "USA"}],
            row_count=2,
            truncated=False,
            execution_time_ms=10,
        )

    monkeypatch.setattr(orchestrator, "get_fake_llm_provider", lambda: spy_llm)
    monkeypatch.setattr(SafeExecutor, "execute", mock_execute)

    # 1. Submit natural-language query
    res = env.client.post(
        "/api/v1/queries",
        json={"connection_id": env.connection_id, "question": "Customers in USA", "max_rows": 100},
        headers=env.headers,
    )
    assert res.status_code == 202, res.text
    query_id = res.json()["query_id"]

    # 2. Wait for completion
    completed = wait_terminal(env, query_id)
    assert completed["status"] == "completed"
    assert completed["origin"] == "natural_language"
    assert completed["row_count"] == 2
    assert completed["results_available"] is True
    assert completed["presentation"] is not None
    assert completed["presentation"]["chart_type"] == "table"
    assert spy_llm.calls == 1
    assert len(exec_calls) == 1


def test_everyday_analytics_manual_sql_journey(analytics_env, completed_run, monkeypatch):
    """Journey 2: Manual SQL edit executes directly with zero LLM calls and origin manual_sql."""
    env = analytics_env
    source = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    exec_calls = []

    def mock_execute(token, **kwargs):
        exec_calls.append(token)
        return QueryResult(
            columns=[
                {"name": "id", "type": "integer", "db_type": "integer"},
                {"name": "country", "type": "string", "db_type": "text"},
            ],
            rows=[{"id": 3, "country": "Canada"}],
            row_count=1,
            truncated=False,
            execution_time_ms=10,
        )

    monkeypatch.setattr(orchestrator, "get_fake_llm_provider", lambda: pytest.fail("provider called on manual SQL"))
    monkeypatch.setattr(SafeExecutor, "execute", mock_execute)

    # Submit manual SQL edit
    res = env.client.post(
        "/api/v1/queries/sql",
        json={
            "connection_id": env.connection_id,
            "source_query_id": source["id"],
            "sql": "SELECT id, country FROM public.customers WHERE country = 'Canada' LIMIT 100;",
            "max_rows": 100,
        },
        headers=env.headers,
    )
    assert res.status_code == 202, res.text
    manual_id = res.json()["query_id"]

    completed = wait_terminal(env, manual_id)
    assert completed["status"] == "completed"
    assert completed["origin"] == "manual_sql"
    assert completed["source_query_id"] == source["id"]
    assert completed["row_count"] == 1
    assert len(exec_calls) == 1


def test_everyday_analytics_saved_question_journey(analytics_env, completed_run, monkeypatch):
    """Journey 3: Discover slots, save question, and rerun with typed parameters directly with zero LLM calls."""
    env = analytics_env
    source = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    # 1. Discover parameters
    disc_res = env.client.get(f"/api/v1/queries/{source['id']}/parameters")
    assert disc_res.status_code == 200
    disc = disc_res.json()
    country_def = next(d for d in disc["definitions"] if d["name"] == "country")

    # 2. Save question
    create_res = env.client.post(
        "/api/v1/saved-questions",
        json={
            "source_query_id": source["id"],
            "title": "Customers by Country",
            "description": "Filter customers by selected country",
            "chart_preference": "table",
            "parameters": [country_def],
        },
        headers=env.headers,
    )
    assert create_res.status_code == 201, create_res.text
    saved = create_res.json()

    # 3. Direct rerun with changed parameter value
    exec_calls = []

    def mock_execute(token, **kwargs):
        exec_calls.append(token)
        return QueryResult(
            columns=[
                {"name": "id", "type": "integer", "db_type": "integer"},
                {"name": "country", "type": "string", "db_type": "text"},
            ],
            rows=[{"id": 4, "country": "UK"}],
            row_count=1,
            truncated=False,
            execution_time_ms=10,
        )

    monkeypatch.setattr(orchestrator, "get_fake_llm_provider", lambda: pytest.fail("provider called on saved question"))
    monkeypatch.setattr(SafeExecutor, "execute", mock_execute)

    run_res = env.client.post(
        f"/api/v1/saved-questions/{saved['id']}/run",
        json={"parameters": {country_def["name"]: "UK"}},
        headers=env.headers,
    )
    assert run_res.status_code == 202, run_res.text
    run_id = run_res.json()["query_id"]

    completed = wait_terminal(env, run_id)
    assert completed["status"] == "completed"
    assert completed["origin"] == "saved_question"
    assert completed["saved_question_id"] == saved["id"]
    assert completed["row_count"] == 1
    assert len(exec_calls) == 1


def test_everyday_analytics_followup_branching_journey(analytics_env, completed_run, monkeypatch):
    """Journey 4: Follow-up lineage branches accurately from selected parent query."""
    env = analytics_env
    # Parent A
    run_a = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    spy_llm = SpyLLMProvider("SELECT id, country FROM public.customers WHERE country = 'USA' AND id > 10 LIMIT 101;")
    exec_calls = []

    def mock_execute(token, **kwargs):
        exec_calls.append(token)
        return QueryResult(
            columns=[
                {"name": "id", "type": "integer", "db_type": "integer"},
                {"name": "country", "type": "string", "db_type": "text"},
            ],
            rows=[{"id": 11, "country": "USA"}],
            row_count=1,
            truncated=False,
            execution_time_ms=10,
        )

    monkeypatch.setattr(orchestrator, "get_fake_llm_provider", lambda: spy_llm)
    monkeypatch.setattr(SafeExecutor, "execute", mock_execute)

    # Follow-up B from parent A
    res_b = env.client.post(
        "/api/v1/queries",
        json={
            "connection_id": env.connection_id,
            "question": "Only with id > 10",
            "parent_query_id": run_a["id"],
            "max_rows": 100,
        },
        headers=env.headers,
    )
    assert res_b.status_code == 202, res_b.text
    run_b_id = res_b.json()["query_id"]

    completed_b = wait_terminal(env, run_b_id)
    assert completed_b["status"] == "completed"
    assert completed_b["origin"] == "follow_up"
    assert completed_b["parent_query_id"] == run_a["id"]


def test_everyday_analytics_stale_context_drift_rejection(analytics_env, completed_run):
    """Journey 5: Follow-up query fails with 409 FOLLOWUP_CONTEXT_STALE when catalog snapshot changes."""
    env = analytics_env
    run_a = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    # Simulate catalog drift by saving a new snapshot with different snapshot_hash
    stale_snapshot = env.snapshot.model_copy(deep=True)
    stale_snapshot.snapshot_hash = "f" * 64
    save_snapshot(stale_snapshot)

    # Attempt follow-up against drifted snapshot
    res = env.client.post(
        "/api/v1/queries",
        json={
            "connection_id": env.connection_id,
            "question": "Only with id > 10",
            "parent_query_id": run_a["id"],
            "max_rows": 100,
        },
        headers=env.headers,
    )
    assert res.status_code == 409, res.text
    data = res.json()
    assert data["error"]["code"] == "FOLLOWUP_CONTEXT_STALE"
