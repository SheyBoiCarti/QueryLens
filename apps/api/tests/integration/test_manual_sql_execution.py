"""Authenticated manual execution, provenance, and policy enforcement."""

import json
import time
import uuid
import pytest
from querylens.domain.query import QueryResult
from querylens.execution.executor import SafeExecutor
from querylens.persistence.repositories.query_runs import QueryRunRepository


def wait_terminal(env, query_id):
    for _ in range(200):
        run = env.client.get(f"/api/v1/queries/{query_id}")
        assert run.status_code == 200, run.text
        if run.json()["status"] in {"completed", "failed", "rejected", "cancelled", "interrupted"}:
            return run.json()
        time.sleep(0.01)
    pytest.fail("Manual run did not become terminal")


def submit(env, sql, **extra):
    return env.client.post(
        "/api/v1/queries/sql",
        headers=env.headers,
        json={"connection_id": env.connection_id, "sql": sql, "max_rows": 100, **extra},
    )


@pytest.mark.parametrize("suffix,cap", [("", None), (" LIMIT 20", 20)])
def test_manual_completes_without_provider_and_retains_author_limit(analytics_env, monkeypatch, suffix, cap):
    env = analytics_env
    calls = []

    def execute(token, **kwargs):
        calls.append(token)
        return QueryResult([{"name": "id", "type": "integer", "db_type": "integer"}], [{"id": 3}], 1, False, 1)

    monkeypatch.setattr(SafeExecutor, "execute", execute)
    import querylens.pipeline.orchestrator as orchestrator

    monkeypatch.setattr(orchestrator, "get_fake_llm_provider", lambda: pytest.fail("direct path used provider"))
    response = submit(env, "SELECT id FROM public.customers" + suffix)
    assert response.status_code == 202, response.text
    completed = wait_terminal(env, response.json()["query_id"])
    assert completed["status"] == "completed", completed
    assert completed["origin"] == "manual_sql"
    assert completed["rows"] == [{"id": 3}]
    assert f"LIMIT {20 if cap else 101}" in completed["sql"]
    run = QueryRunRepository().get(completed["query_id"], env.owner_id)
    context = json.loads(run["run_context_json"])
    assert context["author_limit"] == cap
    assert ("LIMIT" in context["canonical_sql_template"]) == (cap is not None)
    assert run["submitted_sql"] == "SELECT id FROM public.customers" + suffix
    assert len(calls) == 1
    attempt = QueryRunRepository().get_attempts(completed["query_id"])[0]
    assert attempt["prompt_tokens"] == attempt["completion_tokens"] == 0


@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM public.customers",
        "SELECT 1; SELECT 2",
        "SELECT id FROM private.secret",
        "SELECT id FROM public.customers FOR UPDATE",
        "SELECT pg_sleep(1)",
        "SELECT :unbound FROM public.customers",
    ],
)
def test_unsafe_manual_sql_is_terminal_rejected_without_executor(analytics_env, monkeypatch, sql):
    monkeypatch.setattr(SafeExecutor, "execute", lambda *a, **kw: pytest.fail("unsafe SQL reached executor"))
    response = submit(analytics_env, sql)
    assert response.status_code == 202, response.text
    run = wait_terminal(analytics_env, response.json()["query_id"])
    assert run["status"] == "rejected", run


def test_manual_source_is_completed_owned_and_same_connection_before_admission(
    analytics_env, completed_run, monkeypatch
):
    env = analytics_env
    monkeypatch.setattr(SafeExecutor, "execute", lambda *a, **kw: QueryResult([], [], 0, False, 1))
    source = completed_run()
    response = submit(env, "SELECT id FROM public.customers", source_query_id=source["id"])
    assert response.status_code == 202
    assert wait_terminal(env, response.json()["query_id"])["source_query_id"] == source["id"]
    repo = QueryRunRepository()
    foreign_id = str(uuid.uuid4())
    repo.create(foreign_id, env.foreign_id, env.foreign_connection_id, "foreign")
    assert submit(env, "SELECT 1", source_query_id=foreign_id).status_code == 404
    queued_id = str(uuid.uuid4())
    repo.create(queued_id, env.owner_id, env.connection_id, "queued")
    assert submit(env, "SELECT 1", source_query_id=queued_id).status_code == 422


def test_manual_origin_and_lowered_limits(analytics_env, monkeypatch):
    env = analytics_env
    assert (
        env.client.post("/api/v1/queries/sql", json={"connection_id": env.connection_id, "sql": "SELECT 1"},
                        headers={"Origin": "https://foreign.example"}).status_code
        == 403
    )
    from querylens.config import get_settings

    settings = get_settings()
    monkeypatch.setattr(settings, "max_max_rows", 10)
    assert submit(env, "SELECT 1").status_code == 422
    monkeypatch.setattr(settings, "max_max_rows", 1000)
    monkeypatch.setattr(settings, "max_sql_bytes", 40)
    assert submit(env, "SELECT '" + "é" * 20 + "'").status_code == 422


def test_canonical_sql_expansion_respects_byte_budget_and_parameter_defaults(analytics_env, monkeypatch):
    from querylens.config import get_settings
    from querylens.sql.policy import SQLPolicyViolationError, validate_query_artifact

    env = analytics_env
    artifact = validate_query_artifact(
        "SELECT id FROM public.customers", env.connection_id, "postgresql", env.snapshot, 20
    )
    assert artifact.resolved_parameters.max_rows == 20
    assert artifact.author_limit is None
    # The submitted star is small; authorized explicit identifiers and the fetch
    # sentinel must also fit before an execution capability can be returned.
    sql = "SELECT * FROM customers"
    monkeypatch.setattr(get_settings(), "max_sql_bytes", len(sql.encode()) + 1)
    with pytest.raises(SQLPolicyViolationError, match="Canonical SQL"):
        validate_query_artifact(sql, env.connection_id, "postgresql", env.snapshot, 20)


def test_manual_source_wrong_connection_without_authentication(analytics_env, monkeypatch):
    from querylens.persistence.tables import connections

    env = analytics_env
    with env.engine.begin() as conn:
        conn.execute(
            connections.update().where(connections.c.id == env.foreign_connection_id).values(user_id=env.owner_id)
        )
    source_id = str(uuid.uuid4())
    repo = QueryRunRepository()
    repo.create(source_id, env.owner_id, env.foreign_connection_id, "other connection")
    repo.update_state(source_id, "completed")
    assert submit(env, "SELECT 1", source_query_id=source_id).status_code == 422
    env.client.cookies.clear()
    monkeypatch.setattr(SafeExecutor, "execute", lambda *a, **kw: QueryResult([], [], 0, False, 1))
    response = submit(env, "SELECT 1")
    assert response.status_code == 202
    assert wait_terminal(env, response.json()["query_id"])["status"] == "completed"


@pytest.mark.parametrize("partial_catalog", [False, True])
def test_manual_physical_column_alias_lists_reject_without_execution(analytics_env, monkeypatch, partial_catalog):
    from querylens.schema.snapshots import save_snapshot
    from querylens.persistence.tables import connections

    env = analytics_env
    if partial_catalog:
        # Only country is visible; positional aliases cannot safely relabel a
        # hidden first physical column as country.
        snapshot = env.snapshot.model_copy(deep=True)
        snapshot.tables[0].columns = [column for column in snapshot.tables[0].columns if column.name == "country"]
        snapshot.snapshot_hash = snapshot.compute_hash()
        save_snapshot(snapshot)
        with env.engine.begin() as conn:
            conn.execute(
                connections.update()
                .where(connections.c.id == env.connection_id)
                .values(allowed_tables=json.dumps({"public.customers": ["country"]}))
            )
    calls = []

    def execute(*args, **kwargs):
        calls.append(args)
        return QueryResult([], [], 0, False, 1)

    monkeypatch.setattr(SafeExecutor, "execute", execute)
    response = submit(env, "SELECT c.country FROM public.customers AS c (country)")
    assert response.status_code == 202, response.text
    run = wait_terminal(env, response.json()["query_id"])
    assert run["status"] == "rejected", run
    assert calls == []
