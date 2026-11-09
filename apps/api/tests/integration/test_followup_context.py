"""Integration tests for follow-up query submission, prompt budgeting, and inherited lineage (Contract C08)."""

import time
import pytest

from querylens.domain.query import QueryResult
from querylens.execution.executor import SafeExecutor
from querylens.llm.protocol import GeneratedCandidate, LLMUsage


def wait_terminal(env, query_id):
    for _ in range(200):
        run = env.client.get(f"/api/v1/queries/{query_id}")
        assert run.status_code == 200, run.text
        if run.json()["status"] in {"completed", "failed", "rejected", "cancelled", "interrupted"}:
            return run.json()
        time.sleep(0.01)
    pytest.fail("Query run did not become terminal in time")


def test_followup_query_end_to_end_journey(analytics_env, completed_run, monkeypatch):
    """Submitting a follow-up inherits lineage and scope, without provider rows."""
    env = analytics_env
    parent_run = completed_run(sql="SELECT id, country FROM public.customers WHERE country = 'USA';")

    calls = []

    def execute(token, **kwargs):
        calls.append(token)
        return QueryResult([{"name": "id", "type": "integer", "db_type": "integer"}], [{"id": 10}], 1, False, 1)

    monkeypatch.setattr(SafeExecutor, "execute", execute)

    import querylens.pipeline.orchestrator as orchestrator

    provider_calls = []

    class SpyLLMProvider:
        async def generate(self, question, dialect, schema_context, timeout_sec=10.0):
            provider_calls.append({"question": question, "context": schema_context, "dialect": dialect})
            return GeneratedCandidate(
                sql="SELECT id FROM public.customers WHERE country = 'USA' AND id > 5;",
                assumptions=["Follow up filter"],
                requires_clarification=False,
                usage=LLMUsage(prompt_tokens=100, completion_tokens=20, latency_ms=10),
            )

    monkeypatch.setattr(orchestrator, "get_fake_llm_provider", lambda: SpyLLMProvider())

    # Submit follow-up question
    submit_res = env.client.post(
        "/api/v1/queries",
        headers=env.headers,
        json={
            "connection_id": env.connection_id,
            "question": "Only ID greater than 5",
            "parent_query_id": parent_run["id"],
        },
    )
    assert submit_res.status_code == 202, submit_res.text
    query_id = submit_res.json()["query_id"]

    completed = wait_terminal(env, query_id)
    assert completed["status"] == "completed", completed
    assert completed["origin"] == "follow_up"
    assert completed["parent_query_id"] == parent_run["id"]

    # Assert provider received follow-up context and inherited schema
    assert len(provider_calls) == 1
    call = provider_calls[0]
    assert "FOLLOW-UP CONVERSATION HISTORY" in call["context"]
    assert "public.customers" in call["context"]
    assert "TABLE public.customers:" in call["context"]
    # Rows from parent must NOT be leaked into context
    assert "id: 1" not in call["context"]


def test_followup_rejects_foreign_and_incomplete_parent(analytics_env, completed_run):
    """Foreign parent returns 404; incomplete parent returns 422."""
    env = analytics_env
    parent_run = completed_run(sql="SELECT id FROM public.customers;")

    # 1. Incomplete parent returns 422
    from querylens.persistence.repositories.query_runs import QueryRunRepository

    inc_id = "inc_query_run"
    QueryRunRepository().create(inc_id, env.owner_id, env.connection_id, "Incomplete query")
    res_inc = env.client.post(
        "/api/v1/queries",
        headers=env.headers,
        json={
            "connection_id": env.connection_id,
            "question": "Follow up on incomplete",
            "parent_query_id": inc_id,
        },
    )
    assert res_inc.status_code == 422

    # 2. Foreign user attempt on owner parent returns 404
    login_foreign = env.client.post(
        "/api/v1/auth/login",
        json={"email": "analytics-foreign@example.test", "password": env.password},
        headers={"Origin": "http://localhost:5173", "X-QueryLens-Client": "web"},
    )
    foreign_headers = {"Origin": "http://localhost:5173", "X-CSRF-Token": login_foreign.json()["csrf_token"]}

    res_foreign = env.client.post(
        "/api/v1/queries",
        headers=foreign_headers,
        json={
            "connection_id": env.foreign_connection_id,
            "question": "Follow up fragment",
            "parent_query_id": parent_run["id"],
        },
    )
    assert res_foreign.status_code == 404


def test_followup_rejects_stale_parent_drift(analytics_env, completed_run):
    """Catalog drift between parent and follow-up returns 409 FOLLOWUP_CONTEXT_STALE."""
    env = analytics_env
    parent_run = completed_run(sql="SELECT id FROM public.customers;")

    # Simulate catalog drift
    from querylens.domain.schema import CatalogSnapshot, ColumnMetadata, TableMetadata
    from querylens.schema.snapshots import save_snapshot

    drifted_snapshot = CatalogSnapshot(
        connection_id=env.connection_id,
        engine="postgresql",
        tables=[
            TableMetadata(
                namespace="public",
                name="customers",
                columns=[
                    ColumnMetadata(name="id", canonical_type="integer", db_type="integer"),
                    ColumnMetadata(name="new_col", canonical_type="string", db_type="text"),
                ],
            )
        ],
    )
    drifted_snapshot.snapshot_hash = drifted_snapshot.compute_hash()
    save_snapshot(drifted_snapshot)

    res_stale = env.client.post(
        "/api/v1/queries",
        headers=env.headers,
        json={
            "connection_id": env.connection_id,
            "question": "Follow up after drift",
            "parent_query_id": parent_run["id"],
        },
    )
    assert res_stale.status_code == 409
    data = res_stale.json()
    assert data.get("detail", {}).get("error_code") == "FOLLOWUP_CONTEXT_STALE" or "FOLLOWUP_CONTEXT_STALE" in str(data)


def test_required_parent_schema_and_repair_are_never_truncated(analytics_env):
    from types import SimpleNamespace
    from querylens.domain.analytics import ObjectReference
    from querylens.domain.schema import ColumnMetadata
    from querylens.pipeline.context import ContextBudgetError, build_query_context
    from querylens.pipeline.repair_context import assemble_repair_context
    from querylens.pipeline.errors import ClassifiedError
    from querylens.semantics.versions import load_semantic_context

    env = analytics_env
    snapshot = env.snapshot.model_copy(deep=True)
    snapshot.tables[0].columns.extend(
        ColumnMetadata(name=f"required_column_{index}", canonical_type="string", db_type="text")
        for index in range(200)
    )
    inherited = SimpleNamespace(
        required_references=(ObjectReference(namespace="public", table_name="customers"),),
        formatted_text="Essential inherited scope", estimated_tokens=25,
    )
    semantics = load_semantic_context(env.owner_id, env.snapshot)
    with pytest.raises(ContextBudgetError, match="follow-up table"):
        build_query_context(snapshot, "total", 4000, semantics, inherited)
    context = build_query_context(snapshot, "total", 16000, semantics, inherited)
    assert "required_column_199" in context and "Essential inherited scope" in context
    error = ClassifiedError(category="syntax", code="SYNTAX_ERROR", safe_message="Invalid syntax", repairable=True)
    with pytest.raises(ContextBudgetError, match="Required repair context"):
        assemble_repair_context("total", "postgresql", context, "SELECT broken", error, max_tokens=1000)
